"""
kt_lib.py -- kill-test infrastructure.

Design rules (deliberate contrast with the audited Legion codebase):
  * NO silent failures. Every exception is logged with context to errors.jsonl.
  * Atomic JSON writes (tmp + os.replace); append-only JSONL for events.
  * NO keypair handling, NO signing, NO order path. Enforced by self-check (see selfcheck()).
  * Every RPC call is counted against a daily budget.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "logs")

# ----------------------------------------------------------------------------- secret hygiene
# Any value registered here is masked everywhere: logs, errors, stdout. Even if a URL
# containing a key is echoed back by `requests` in an exception, it cannot reach disk.
_SECRETS: set[str] = set()


def register_secret(v: Any) -> None:
    if isinstance(v, str) and len(v) >= 8:
        _SECRETS.add(v)


def redact_text(s: str) -> str:
    if not isinstance(s, str) or not s:
        return s
    for sec in _SECRETS:
        if sec:
            s = s.replace(sec, "***")
    # belt-and-braces patterns in case a secret was never registered
    s = re.sub(r"(api-key=)[A-Za-z0-9\-_]+", r"\1***", s, flags=re.I)
    s = re.sub(r"([?&](?:api_?key|apikey|key|token|auth)=)[A-Za-z0-9\-_.]+", r"\1***", s, flags=re.I)
    s = re.sub(r"(/v2/)[A-Za-z0-9\-_]{16,}", r"\1***", s)
    s = re.sub(r"(/v1/)[A-Za-z0-9\-_]{16,}", r"\1***", s)
    return s

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

JUP_PRICE_HOSTS = ["https://lite-api.jup.ag/price/v3", "https://api.jup.ag/price/v3"]
JUP_QUOTE_HOSTS = ["https://lite-api.jup.ag/swap/v1/quote", "https://api.jup.ag/swap/v1/quote"]
DEXSCREENER = "https://api.dexscreener.com/latest/dex/tokens"
COINBASE_SOL = "https://api.coinbase.com/v2/prices/SOL-USD/spot"

DECIMALS = {WSOL: 9, USDC: 6, USDT: 6}
HTTP_TIMEOUT = 12


# ----------------------------------------------------------------------------- config
def load_config(path: str | None = None) -> dict:
    path = path or os.path.join(HERE, "config.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Keys excluded from the config fingerprint: credentials/paths and documentation, plus
# purely operational settings that cannot affect a measurement. Without this, a comment
# edit or a poll-interval tweak would invalidate an otherwise valid dataset.
_FP_IGNORE_EXACT = {
    "log_dir", "legion_config_path", "rpc_url_env", "ws_url_env", "fallback_rpc_url",
    "extra_wallets", "max_rpc_calls_per_day",
    "poll_fallback_enabled", "use_websocket",
    # poll_interval_sec and poll_rotation_batch used to be listed above as "purely
    # operational settings that cannot affect a measurement". That is false for v3: the
    # pre-registration derives Tier B's rotation -- and through it the worst-case latency
    # and the per-wallet sampling density -- directly from (N/B) x poll_interval_sec.
    # Changing either changes the sampling regime, so both are now fingerprinted. (They were
    # also 120 and 20 in config while the registration assumed 60 and 20, which is part of
    # why the registered 900s rotation was never achieved.)
    #
    # max_signal_age_sec used to be listed here as "data-cleaning hygiene only: changes
    # WHICH stale signals are discarded, not the measurement". That was true in v1, where
    # the ingest gate (180s) was WIDER than the primary pool (60s) and therefore could not
    # bind. It is false for v3: the registered allowance is <=900s, so the 180s gate DID
    # define the primary pool -- it discarded 59% of Tier B and 0% of Tier A, quietly
    # steering the test onto the frequency-ranked tier. Worse, because it was ignored here,
    # correcting it left the fingerprint unchanged and would have silently POOLED the fixed
    # data with the data it invalidated. It is a substantive parameter now; do not re-add it.
    # max_signal_latency_sec_for_primary is substantive for the same reason (it defines the
    # v1 primary pool), which is why v3 got its own max_signal_latency_sec_for_v3 key.
}


def substantive_config(cfg: dict) -> dict:
    """Strip documentation, credential and operational keys, recursively."""
    out = {}
    for k, v in cfg.items():
        if k.startswith("_") or k in _FP_IGNORE_EXACT:
            continue
        out[k] = substantive_config(v) if isinstance(v, dict) else v
    return out


# ----------------------------------------------------------------------------- credentials
# STRICT ALLOWLIST. Only these dotted paths are ever read out of a Legion config file.
# `solana.toke_private_key` and `solana.toke_seed_phrase` live in the same file and are
# deliberately NOT on this list -- they are never read, never returned, never logged.
CRED_ALLOWLIST = [
    ("solana.helius_api_key", "helius"),
    ("helius_api_key", "helius"),
    ("rpc.getblock_url", "getblock_url"),
    ("rpc.getblock_key", "getblock_key"),
    ("rpc.alchemy_key", "alchemy"),
]

# Names that must never be read, kept only so we can CONFIRM we refused them.
FORBIDDEN_FIELD_HINTS = ("private", "secret", "seed", "mnemonic", "password", "passphrase")


def _looks_like_key_material(v: Any) -> bool:
    """Seed phrases contain spaces; long base58 strings are private keys. Refuse both."""
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s:
        return False
    if " " in s:                 # a seed phrase
        return True
    if len(s) > 60:              # a base58 secret key
        return True
    return False


def load_rpc_credentials(path: str | None) -> dict:
    """
    Build RPC/WS endpoints from a Legion config, reading ONLY allowlisted RPC fields.

    Returns:
      rpc_urls / ws_urls : priority-ordered candidate endpoints (secrets registered for masking)
      found              : which allowlisted fields were present
      refused            : field names skipped because they looked like key material
      error              : any read/parse problem (never swallowed)
    """
    res: dict[str, Any] = {"rpc_urls": [], "ws_urls": [], "found": [], "refused": [],
                           "error": None, "path": path, "available": []}
    if not path or not os.path.exists(path):
        res["error"] = f"config not found: {path}"
        return res
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
        return res

    # record available field NAMES only (never values) so a miss is diagnosable
    def names(d, prefix=""):
        out = []
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, dict):
                    out += names(v, f"{prefix}{k}.")
                else:
                    out.append(f"{prefix}{k}")
        return out
    res["available"] = names(cfg)

    helius = getblock_url = getblock_key = alchemy = None
    for dotted, kind in CRED_ALLOWLIST:
        cur = cfg
        ok = True
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if not ok or not isinstance(cur, str) or not cur.strip():
            continue
        val = cur.strip()
        if kind in ("helius", "alchemy", "getblock_key") and _looks_like_key_material(val):
            res["refused"].append(dotted)      # wrong field, or someone renamed things
            continue
        res["found"].append(dotted)
        register_secret(val)
        if kind == "helius":
            helius = val
        elif kind == "getblock_url":
            getblock_url = val
        elif kind == "getblock_key":
            getblock_key = val
        elif kind == "alchemy":
            alchemy = val

    if helius:
        res["rpc_urls"].append(f"https://mainnet.helius-rpc.com/?api-key={helius}")
        res["ws_urls"].append(f"wss://mainnet.helius-rpc.com/?api-key={helius}")
    if getblock_url:
        res["rpc_urls"].append(getblock_url)                    # already a full URL
    if alchemy:
        res["rpc_urls"].append(f"https://solana-mainnet.g.alchemy.com/v2/{alchemy}")
        res["ws_urls"].append(f"wss://solana-mainnet.g.alchemy.com/v2/{alchemy}")
    return res


# ----------------------------------------------------------------------------- store
class Store:
    """Append-only JSONL + atomic JSON. Never raises on a logging failure."""

    def __init__(self, log_dir: str = LOG_DIR):
        self.dir = log_dir
        os.makedirs(self.dir, exist_ok=True)
        self.signals = os.path.join(self.dir, "signals.jsonl")
        self.errors = os.path.join(self.dir, "errors.jsonl")
        self.rpc_log = os.path.join(self.dir, "rpc_calls.jsonl")
        self.activity = os.path.join(self.dir, "activity.log")
        self._lock = threading.Lock()

    def _append(self, path: str, obj: dict) -> None:
        obj = dict(obj)
        obj.setdefault("ts", datetime.now(timezone.utc).isoformat())
        line = redact_text(json.dumps(obj, ensure_ascii=False, default=str))
        with self._lock:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as e:                      # last-resort stderr, never swallowed
                print(f"[store] FAILED to append to {path}: {e}", file=sys.stderr)

    def signal(self, obj: dict) -> None:
        self._append(self.signals, obj)

    def error(self, where: str, exc: BaseException | str, **ctx: Any) -> None:
        self._append(self.errors, {
            "where": where,
            "error": f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc),
            "ctx": ctx,
        })

    def rpc_call(self, method: str, ok: bool, n_calls: int) -> None:
        self._append(self.rpc_log, {"method": method, "ok": ok, "n_calls": n_calls})

    def note(self, msg: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        line = redact_text(f"[{stamp}Z] {msg}")
        print(line, flush=True)
        try:
            with open(self.activity, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            print(f"[store] activity log failed: {e}", file=sys.stderr)

    def read_signals(self) -> list[dict]:
        out = []
        if not os.path.exists(self.signals):
            return out
        with open(self.signals, "r", encoding="utf-8") as f:
            for ln, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except Exception as e:
                    self.error("read_signals", e, line=ln)
        return out

    @staticmethod
    def write_json_atomic(path: str, obj: Any) -> None:
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=1, default=str)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise


# ----------------------------------------------------------------------------- rpc
class Rpc:
    """
    Minimal Solana JSON-RPC client with a hard daily call budget, request throttling
    and 429 backoff. Throttling matters: Helius returns 429 on bursts, and a client
    that hammers it (as the audited Legion pipeline did) silently loses transactions.
    """

    MIN_INTERVAL = 0.25          # <= 4 req/s, comfortably under typical free-tier limits

    def __init__(self, urls: str | list[str], store: Store, max_calls_per_day: int = 40000):
        if isinstance(urls, str):
            urls = [urls]
        # de-duplicate, preserve priority order
        seen, ordered = set(), []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                ordered.append(u)
        self.urls = ordered
        self.idx = 0
        self.store = store
        self.max = max_calls_per_day
        self._n = 0
        self._day = datetime.now(timezone.utc).date()
        self._lock = threading.Lock()
        self._last_call = 0.0
        self.rate_limit_hits = 0
        self.failovers = 0
        self.session = requests.Session()

    @property
    def url(self) -> str | None:
        return self.urls[self.idx] if self.urls else None

    def pick_healthy(self, probe_sig: str | None = None, timeout: int = 12) -> str | None:
        """
        Adopt the first candidate that actually RETURNS DATA.

        Deliberately probes with getTransaction on a known-good signature rather than
        getHealth: some providers answer 200/null for real calls while reporting healthy,
        which is worse than being down (the audited Legion pipeline had the same class of
        silent-empty-result failure). A null result counts as unhealthy.
        """
        for i, u in enumerate(self.urls):
            tag = redact_text(u)
            try:
                if probe_sig:
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                               "params": [probe_sig, {"encoding": "jsonParsed",
                                                      "maxSupportedTransactionVersion": 1}]}
                else:
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth", "params": []}
                r = self.session.post(u, json=payload, timeout=timeout)
                if r.status_code == 429:
                    self.store.note(f"rpc probe: {tag} -> 429 rate limited")
                    continue
                if r.status_code != 200:
                    self.store.note(f"rpc probe: {tag} -> HTTP {r.status_code}")
                    continue
                d = r.json()
                if "error" in d:
                    self.store.note(f"rpc probe: {tag} -> rpc error {str(d.get('error'))[:50]}")
                    continue
                if probe_sig and not d.get("result"):
                    self.store.note(f"rpc probe: {tag} -> HEALTHY BUT EMPTY (null result) — skipping")
                    continue
                self.idx = i
                self.store.note(f"rpc probe: using {tag} (returned data)")
                return u
            except Exception as e:
                self.store.note(f"rpc probe: {tag} -> {type(e).__name__}")
        self.store.note("rpc probe: no candidate returned data; using first and rotating on failure")
        return self.url

    def _rotate(self, reason: str) -> None:
        if len(self.urls) > 1:
            self.idx = (self.idx + 1) % len(self.urls)
            self.failovers += 1
            self.store.note(f"RPC failover #{self.failovers} -> {redact_text(self.url)} ({reason})")

    def _roll_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._n = 0

    @property
    def calls_today(self) -> int:
        return self._n

    def budget_left(self) -> int:
        self._roll_day()
        return self.max - self._n

    def _throttle(self) -> None:
        wait = self.MIN_INTERVAL - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def call(self, method: str, params: list, timeout: int = HTTP_TIMEOUT, max_retries: int = 4) -> Any:
        self._roll_day()
        with self._lock:
            if self._n >= self.max:
                self.store.error("rpc.budget", f"daily RPC budget exhausted ({self.max})", method=method)
                return None
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        delay = 0.6
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            with self._lock:
                self._n += 1
                n = self._n
            self._throttle()
            try:
                r = self.session.post(self.url, json=payload, timeout=timeout)
                if r.status_code == 429:
                    self.rate_limit_hits += 1
                    self.store.error("rpc.429", f"rate limited, backoff {delay:.1f}s",
                                     method=method, attempt=attempt + 1)
                    time.sleep(delay)
                    delay *= 2
                    continue
                r.raise_for_status()
                d = r.json()
            except Exception as e:
                last_exc = e
                self.store.error("rpc.call", e, method=method, attempt=attempt + 1)
                time.sleep(min(delay, 4.0))
                delay *= 2
                continue
            self.store.rpc_call(method, True, n)
            if "error" in d:
                self.store.error("rpc.result", str(d["error"]), method=method)
                return None
            return d.get("result")
        self.store.rpc_call(method, False, self._n)
        if last_exc is not None:
            self.store.error("rpc.give_up", last_exc, method=method)
        else:
            self.store.error("rpc.give_up", "rate limited on every attempt", method=method)
        self._rotate("give-up on this endpoint")
        return None

    def get_transaction(self, sig: str) -> dict | None:
        return self.call("getTransaction", [
            sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                  "commitment": "confirmed"},
        ])

    def get_signatures(self, address: str, limit: int = 5) -> list | None:
        return self.call("getSignaturesForAddress", [address, {"limit": limit}], timeout=10)


# ----------------------------------------------------------------------------- swap parsing
def _ui_amount(bal: dict) -> float | None:
    """Decimal-adjusted amount, preferring uiAmount then uiAmountString then raw."""
    ta = bal.get("uiTokenAmount") or {}
    for k in ("uiAmount", "uiAmountString"):
        v = ta.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    v = ta.get("amount")
    try:
        return float(v)
    except Exception:
        return None


def _token_deltas(tx: dict, owner: str) -> dict[str, float]:
    """Net token delta per mint for `owner`, in decimal-adjusted units."""
    meta = tx.get("meta") or {}
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []
    acc: dict[str, float] = {}
    for bal in pre:
        if bal.get("owner") != owner:
            continue
        amt = _ui_amount(bal)
        if amt is not None:
            acc[bal.get("mint")] = acc.get(bal.get("mint"), 0.0) - amt
    for bal in post:
        if bal.get("owner") != owner:
            continue
        amt = _ui_amount(bal)
        if amt is not None:
            acc[bal.get("mint")] = acc.get(bal.get("mint"), 0.0) + amt
    return {m: v for m, v in acc.items() if abs(v) > 0}


def parse_swap(tx: dict, wallet: str, quote_mints: dict[str, str]) -> dict:
    """
    Classify a wallet's swap. Returns a dict that ALWAYS has 'parse_ok'.
    Never returns None and never silently drops: failures carry a reason.
    """
    out: dict = {
        "parse_ok": False, "reason": None, "action": None, "mint": None,
        "ui_amount": None, "sol_delta": None, "fee_lamports": None,
        "quote_asset": None, "slot": None, "block_time": None, "err": None,
    }
    if not isinstance(tx, dict):
        out["reason"] = "tx_not_dict"
        return out
    meta = tx.get("meta")
    if not isinstance(meta, dict):
        out["reason"] = "no_meta"
        return out
    out["err"] = meta.get("err")
    out["fee_lamports"] = meta.get("fee")
    out["slot"] = tx.get("slot")
    out["block_time"] = tx.get("blockTime")

    if meta.get("err") is not None:
        out["reason"] = "tx_failed"
        return out

    try:
        msg = tx["transaction"]["message"]
        keys = msg.get("accountKeys") or []
        pubkeys = [k.get("pubkey") if isinstance(k, dict) else k for k in keys]
        if wallet not in pubkeys:
            out["reason"] = "wallet_not_in_tx"
            return out
        idx = pubkeys.index(wallet)
        signer = bool(keys[idx].get("signer")) if isinstance(keys[idx], dict) else False

        pre_b = (meta.get("preBalances") or [])
        post_b = (meta.get("postBalances") or [])
        if idx >= len(pre_b) or idx >= len(post_b):
            out["reason"] = "balance_arrays_short"
            return out
        lamport_delta = post_b[idx] - pre_b[idx]
        fee = int(meta.get("fee") or 0)
        if signer:
            lamport_delta += fee          # add fee back so delta reflects the trade, not the cost
        out["sol_delta"] = lamport_delta

        deltas = _token_deltas(tx, wallet)
        if not deltas:
            out["reason"] = "no_token_delta"
            return out

        # WSOL ATA movement is economically native SOL: fold it in.
        wsol_delta_raw = deltas.pop(WSOL, 0.0)
        sol_total = lamport_delta + wsol_delta_raw

        # what did we RECEIVE that is not a quote asset?
        received = {m: d for m, d in deltas.items() if d > 0 and m not in quote_mints}
        gave = {m: -d for m, d in deltas.items() if d < 0 and m not in quote_mints}

        if received:
            mint = max(received, key=received.get)
            out["action"] = "BUY"
            out["mint"] = mint
            out["ui_amount"] = received[mint]
            out["quote_asset"] = "SOL" if sol_total < 0 else "STABLE"
            out["parse_ok"] = True
            return out
        if gave:
            mint = max(gave, key=gave.get)
            out["action"] = "SELL"
            out["mint"] = mint
            out["ui_amount"] = gave[mint]
            out["quote_asset"] = "SOL" if sol_total > 0 else "STABLE"
            out["parse_ok"] = True
            return out
        out["reason"] = "no_non_quote_token_movement"
        return out
    except Exception as e:
        out["reason"] = f"exception:{type(e).__name__}:{e}"
        return out


# ----------------------------------------------------------------------------- prices
class Prices:
    """
    Price + quote client WITH a real rate limiter and 429 backoff.

    The audited Legion pipeline hammered DexScreener with 8 unthrottled threads and had a
    dead pacing constant; here every host is throttled and 429s trigger backoff + retry,
    and any final failure is logged rather than swallowed.
    """

    MIN_INTERVAL = {"dexscreener": 0.55, "jupiter": 0.35, "coinbase": 0.5}

    def __init__(self, store: Store):
        self.store = store
        self.session = requests.Session()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._sol_cache: tuple[float, float] | None = None
        self._last: dict[str, float] = {}
        self._dex_block_until = 0.0
        self.rate_limit_hits = 0

    def _throttle(self, host_key: str) -> None:
        iv = self.MIN_INTERVAL.get(host_key, 0.25)
        prev = self._last.get(host_key)
        if prev is not None:
            wait = iv - (time.time() - prev)
            if wait > 0:
                time.sleep(wait)
        self._last[host_key] = time.time()

    def _get_json(self, url: str, host_key: str = "dexscreener",
                  timeout: int = HTTP_TIMEOUT, max_retries: int = 3) -> Any:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            self._throttle(host_key)
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 429:
                    self.rate_limit_hits += 1
                    self.store.error("prices.429", f"rate limited, backoff {delay:.1f}s",
                                     url=url[:90], attempt=attempt + 1)
                    time.sleep(delay)
                    delay *= 2
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_exc = e
                time.sleep(min(delay, 4.0))
                delay *= 2
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"exhausted retries: {url[:90]}")

    def sol_price(self, ttl: float = 60.0) -> float | None:
        if self._sol_cache and time.time() - self._sol_cache[0] < ttl:
            return self._sol_cache[1]
        for url in (f"{JUP_PRICE_HOSTS[0]}?ids={WSOL}", COINBASE_SOL):
            hk = "jupiter" if "jup.ag" in url else "coinbase"
            try:
                d = self._get_json(url, host_key=hk)
                if isinstance(d, dict) and "data" in d:
                    p = float(d["data"]["amount"]); self._sol_cache = (time.time(), p); return p
                node = d.get(WSOL) if isinstance(d, dict) else None
                if isinstance(node, dict):
                    for k in ("usdPrice", "price", "usd"):
                        if isinstance(node.get(k), (int, float)):
                            p = float(node[k]); self._sol_cache = (time.time(), p); return p
            except Exception as e:
                self.store.error("prices.sol_price", e, url=url)
        return None

    def price(self, mint: str, ttl: float = 20.0) -> dict:
        """
        Return {'price', 'liq_usd', 'source'}.

        Jupiter is the PRIMARY price source (reliable, batchable). DexScreener is consulted
        best-effort for liquidity and as a fallback; if it rate-limits, that host is skipped
        for 60s rather than retried on every call.
        """
        hit = self._cache.get(mint)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        res = {"price": None, "liq_usd": None, "source": None}

        p = self.price_fast(mint, ttl=ttl)
        if p:
            res["price"] = p
            res["source"] = "jupiter"

        if time.time() >= self._dex_block_until:
            try:
                d = self._get_json(f"{DEXSCREENER}/{mint}", host_key="dexscreener", max_retries=2)
                pairs = (d or {}).get("pairs") or []
                if pairs:
                    own = [x for x in pairs if ((x.get("baseToken") or {}).get("address") == mint)]
                    pool = own or pairs
                    best = max(pool, key=lambda x: float(((x.get("liquidity") or {}).get("usd") or 0)))
                    res["liq_usd"] = float(((best.get("liquidity") or {}).get("usd") or 0)) or None
                    if res["price"] is None:
                        try:
                            res["price"] = float(best.get("priceUsd"))
                            res["source"] = "dexscreener"
                        except Exception:
                            pass
            except Exception as e:
                self.store.error("prices.dexscreener", e, mint=mint)
                self._dex_block_until = time.time() + 60.0
                self.store.note("dexscreener throttled; skipping that host for 60s")

        if res["price"] == 0:
            res["price"] = None
        self._cache[mint] = (time.time(), res)
        return res

    def price_fast(self, mint: str, ttl: float = 10.0) -> float | None:
        """
        Jupiter-only price, for the high-frequency forward-tracking path.
        Deliberately avoids DexScreener, which rate-limits aggressively; the entry price
        (where liquidity matters) still uses the full DexScreener-first `price()`.
        """
        key = "fast:" + mint
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1].get("price")
        out = {"price": None, "source": None}
        for host in JUP_PRICE_HOSTS:
            try:
                d = self._get_json(f"{host}?ids={mint}", host_key="jupiter")
                node = (d or {}).get(mint)
                if isinstance(node, dict):
                    for k in ("usdPrice", "price", "usd"):
                        if isinstance(node.get(k), (int, float)) and float(node[k]) > 0:
                            out = {"price": float(node[k]), "source": "jupiter"}
                            break
                if out["price"]:
                    break
            except Exception as e:
                self.store.error("prices.price_fast", e, mint=mint, host=host)
        self._cache[key] = (time.time(), out)
        return out["price"]

    def quote_buy_two_sizes(self, mint: str, big_usd: float, small_usd: float = 1.0) -> dict:
        """
        Genuine slippage, independent of the mid-price source.

        Quoting the same route at a small and a large notional and taking the difference in
        effective price measures REAL price impact from pool depth. This avoids the trap of
        comparing a Jupiter quote against a Jupiter mid, which forces slippage toward zero
        by construction (that flaw made the first run's friction meaningless).
        """
        out = {"ok": False, "reason": None, "slippage_pct": None,
               "impact_pct": None, "effective_small": None, "effective_big": None}
        def _q(usd):
            amt = int(round(usd * 1_000_000))
            if amt <= 0:
                return None
            for host in JUP_QUOTE_HOSTS:
                try:
                    d = self._get_json(
                        f"{host}?inputMint={USDC}&outputMint={mint}&amount={amt}"
                        f"&slippageBps=500&restrictIntermediateTokens=true",
                        host_key="jupiter", timeout=10)
                    o = d.get("outAmount")
                    if not o:
                        continue
                    tok = float(o) / 1e6
                    if tok > 0:
                        return usd / tok
                except Exception as e:
                    self.store.error("prices.quote_two_sizes", e, mint=mint, usd=usd)
            return None
        eff_small = _q(small_usd)
        eff_big = _q(big_usd)
        if eff_small and eff_big and eff_small > 0:
            out["effective_small"] = eff_small
            out["effective_big"] = eff_big
            out["impact_pct"] = max(0.0, (eff_big - eff_small) / eff_small * 100.0)
            out["slippage_pct"] = out["impact_pct"]
            out["ok"] = True
        else:
            out["reason"] = "quote_failed"
        return out

    def quote_buy(self, mint: str, usd: float, sol_usd: float | None) -> dict:
        """
        Live Jupiter quote for buying `usd` worth of `mint` with USDC.
        Returns effective price and MEASURED slippage vs the mid price.
        """
        out = {"ok": False, "reason": None, "effective_price": None,
               "slippage_pct": None, "price_impact_pct": None, "tokens_out": None}
        mid = self.price(mint).get("price")
        amount_in = int(round(usd * 1_000_000))          # USDC has 6 decimals
        if amount_in <= 0:
            out["reason"] = "bad_notional"; return out
        for host in JUP_QUOTE_HOSTS:
            try:
                d = self._get_json(
                    f"{host}?inputMint={USDC}&outputMint={mint}&amount={amount_in}"
                    f"&slippageBps=500&restrictIntermediateTokens=true",
                    host_key="jupiter", timeout=10)
                out_amount = d.get("outAmount")
                if not out_amount:
                    out["reason"] = f"no_out_amount:{str(d)[:120]}"; continue
                tokens = float(out_amount) / (10 ** 6)   # assume 6dp for pump.fun-style mints
                if tokens <= 0:
                    out["reason"] = "zero_tokens"; continue
                eff = usd / tokens
                out["tokens_out"] = tokens
                out["effective_price"] = eff
                try:
                    out["price_impact_pct"] = abs(float(d.get("priceImpactPct") or 0)) * 100
                except Exception:
                    out["price_impact_pct"] = None
                if mid and mid > 0:
                    out["slippage_pct"] = max(0.0, (eff - mid) / mid * 100.0)
                out["ok"] = True
                out["host"] = host
                return out
            except Exception as e:
                self.store.error("prices.quote_buy", e, mint=mint, host=host)
                out["reason"] = f"{type(e).__name__}"
        return out


# ----------------------------------------------------------------------------- friction
def friction_pct(slippage_pct_per_side: float, dex_fee_pct_per_side: float,
                 gas_lamports_per_tx: float, sol_usd: float | None,
                 notional_usd: float) -> float:
    """Total round-trip friction as a percentage of notional."""
    gas_pct = 0.0
    if sol_usd and notional_usd > 0:
        gas_pct = (2.0 * gas_lamports_per_tx / 1e9 * sol_usd / notional_usd) * 100.0
    return 2.0 * (dex_fee_pct_per_side + slippage_pct_per_side) + gas_pct


# ----------------------------------------------------------------------------- safety self-check
# Assembled from fragments so this file does not trip its own scan.
FORBIDDEN = [
    "Key" + "pair",
    "send" + "Transaction",
    "sendRaw" + "Transaction",
    "sign" + "Transaction",
    "from_secret" + "_key",
    "private" + "_key",
    "seed" + "_phrase",
    "request" + "Airdrop",
]


def selfcheck(verbose: bool = True) -> list[str]:
    """
    Refuse to run if anything resembling a signing/order path exists in this rig.
    Proves the 'structurally paper-only' claim instead of asserting it.
    """
    hits: list[str] = []
    for fn in sorted(os.listdir(HERE)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(HERE, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if line.lstrip().startswith("#"):
                        continue
                    for tok in FORBIDDEN:
                        if tok in line:
                            hits.append(f"{fn}:{i}: {tok}")
        except Exception as e:
            hits.append(f"{fn}: unreadable ({e})")
    if verbose:
        if hits:
            print("SELF-CHECK FAILED - possible signing/order code present:")
            for h in hits:
                print("   ", h)
        else:
            print("SELF-CHECK PASSED - no keypair/signing/order tokens found in this rig.")
    return hits
