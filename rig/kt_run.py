"""
kt_run.py -- kill-test runner.

  python kt_run.py selftest          # safety self-check + live parse of a known signature
  python kt_run.py import <sig> <wallet>   # ingest one historical signature (verification)
  python kt_run.py run               # detect + forward-track (the actual test)
  python kt_run.py track             # forward-track only (catch-up pass)
  python kt_run.py status            # live counters

PAPER ONLY. Places no orders, holds no keys.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kt_lib import (FORBIDDEN_FIELD_HINTS, HERE, USDC, USDT, WSOL, Prices, Rpc, Store,
                    friction_pct, load_config, load_rpc_credentials, parse_swap,
                    redact_text, selfcheck)

PUBLIC_WS = "wss://api.mainnet-beta.solana.com"

# Empirically verified to DELIVER logsSubscribe notifications (probe_ws.py, ~1s latency).
# Free, no key. Provider websockets (Alchemy/dRPC) connect and subscribe but push nothing,
# which silently leaves detection to the slow poll -- the root cause of 120s latencies.
PREFERRED_WS = [
    "wss://api.mainnet-beta.solana.com",
    "wss://api.mainnet.solana.com",
]
WS_SILENCE_TIMEOUT_SEC = 90.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_wallets(cfg: dict, store: Store) -> list[str]:
    """Wallets to watch: union of configured sources + extras, capped."""
    seen: list[str] = []
    for src in cfg.get("wallet_sources", []):
        try:
            with open(src, "r", encoding="utf-8") as f:
                d = json.load(f)
            rows = d.get("wallets", d) if isinstance(d, dict) else d
            for r in rows:
                a = r.get("address") if isinstance(r, dict) else r
                if isinstance(a, str) and 32 <= len(a) <= 44 and a not in seen:
                    seen.append(a)
        except Exception as e:
            store.error("load_wallets", e, src=src)
    for a in cfg.get("extra_wallets", []):
        if a not in seen:
            seen.append(a)
    cap = int(cfg.get("max_wallets", 80))
    if len(seen) > cap:
        store.note(f"wallet list {len(seen)} exceeds cap {cap}; truncating")
        seen = seen[:cap]
    return seen


def config_fingerprint(cfg: dict) -> str:
    """Fingerprint the SUBSTANTIVE test parameters only (see kt_lib.substantive_config)."""
    from kt_lib import substantive_config
    return hashlib.sha256(
        json.dumps(substantive_config(cfg), sort_keys=True).encode()).hexdigest()[:16]


class Rig:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = Store(os.path.join(HERE, cfg.get("log_dir", "logs")))
        env_rpc = (os.environ.get(cfg.get("rpc_url_env", ""), "") or "").strip()
        env_ws = (os.environ.get(cfg.get("ws_url_env", ""), "") or "").strip()
        self.creds = load_rpc_credentials(cfg.get("legion_config_path"))
        cand_rpc = (([env_rpc] if env_rpc else []) + self.creds["rpc_urls"]
                    + [cfg.get("fallback_rpc_url", "")])
        cand_ws = ([env_ws] if env_ws else []) + self.creds["ws_urls"]
        self.rpc_candidates = [u for u in cand_rpc if u]
        self.store.note(f"rpc candidates: {[redact_text(u) for u in self.rpc_candidates]}")
        if env_rpc:
            self.cred_source = "environment variable"
        elif self.creds["rpc_urls"]:
            self.cred_source = f"legion config ({', '.join(self.creds['found'])})"
        else:
            self.cred_source = "public fallback (no credentials found)"

        self.rpc = Rpc(self.rpc_candidates, self.store,
                       int(cfg["detection"]["max_rpc_calls_per_day"]))
        probe_sig = None
        try:
            b = _recorded_buys(1)
            probe_sig = b[0]["signature"] if b else None
        except Exception as e:
            self.store.error("probe_sig", e)
        self.rpc.pick_healthy(probe_sig=probe_sig)
        self.rpc_url = self.rpc.url or ""
        # v3.2: seconds per slot is MEASURED in _calibrate_clock, not assumed. The previous
        # hard-coded 0.4 s/slot inflated every slot-based latency by ~1.84x: on 2026-10-10
        # block_time-vs-slot deltas implied 0.218 s/slot across four independent pairs, and
        # recomputing the slot latencies at that rate reproduced the wall-clock latencies to
        # within 1-3s. It also biased clock_offset by ~+3.6s, since the calibration advances
        # a reference block's blockTime by (slot - ref) * slot_sec with ref = slot - 20.
        self.slot_sec: float = 0.4
        self.clock_offset_sec = self._calibrate_clock()

        # websocket choice tracks the RPC: match host, else public
        self._cand_ws = cand_ws
        self.ws_url = self._choose_ws()

        self.prices = Prices(self.store)
        self.wallets = load_wallets(cfg, self.store)

        # ---- v3.1 tiered tracking (see PREREGISTRATION_v3.md amendment) --------------
        # Tier A: self.wallets above -- websocket-capable (~20), frequency-ranked, and so
        #         NOT able to answer H1 on its own (it is the bias v1 identified).
        # Tier B: the full universe, polled in rotation for unbiased coverage over time.
        self._tierA = set(self.wallets)
        self.poll_wallets = list(self.wallets)
        u_src = cfg.get("poll_universe_source")
        if u_src:
            try:
                uni = load_wallets({**cfg, "wallet_sources": [u_src]}, self.store)
                if uni:
                    self.poll_wallets = uni
                    self.store.note(
                        f"v3.2 TIERED: ws on {len(self.wallets)} (tier A), "
                        f"poll rotation over {len(self.poll_wallets)} (tier B)")
            except Exception as e:
                self.store.error("load_poll_universe", e)
        self.quote_mints = cfg["quote_mints"]
        self.horizons = [int(h) for h in cfg["horizons_sec"]]
        self.fp = config_fingerprint(cfg)
        self.seen_sigs: set[str] = set()
        # v3.2: signatures rejected by poll_once's recency pre-filter. Kept separate from
        # seen_sigs so each is counted/logged ONCE instead of on every rotation -- otherwise
        # a dormant wallet's old signatures would grow errors.jsonl without bound.
        self._stale_sigs: set[str] = set()
        self.pending: dict[str, dict] = {}
        self.counters = {"detected": 0, "buys": 0, "signals": 0, "skipped": 0, "forward": 0}
        self._load_existing()

    def _calibrate_clock(self) -> float:
        """
        Measure (chain_time - local_time) so wall-clock latency is not skewed.

        IMPORTANT: the referenced block is OLDER than now by (slot - ref) slots, so its
        blockTime must be advanced by that age before comparing with the local clock.
        Omitting that term biased the offset by ~-8s and made wall latency look negative
        (e.g. wall=-6.8s while the clock-free slot latency was correctly 0.0s).
        """
        try:
            slot = self.rpc.call("getSlot", [{"commitment": "confirmed"}])
            if not slot:
                return 0.0
            ref = max(1, int(slot) - 20)
            bt = self.rpc.call("getBlockTime", [ref])
            if not bt:
                return 0.0
            # v3.2: measure seconds-per-slot from two dated reference slots instead of
            # assuming 0.4. Self-correcting across epochs, and it removes the ~+3.6s bias
            # that a wrong constant injected into this offset (20 slots * 0.182s error).
            ref2 = max(1, ref - 40)
            bt2 = self.rpc.call("getBlockTime", [ref2])
            if bt2 and (ref - ref2) > 0:
                measured = (float(bt) - float(bt2)) / float(ref - ref2)
                if 0.05 < measured < 2.0:            # sanity: reject garbage/timestamps
                    self.slot_sec = measured
            age_sec = max(0, (int(slot) - ref)) * self.slot_sec
            chain_now = float(bt) + age_sec
            offset = chain_now - time.time()
            self.store.note(
                f"clock calibration: chain_time - local_time = {offset:+.1f}s "
                f"(block age {age_sec:.1f}s compensated at {self.slot_sec:.3f}s/slot)"
                f"{'  (LOCAL CLOCK SKEWED - corrected)' if abs(offset) > 5 else ''}")
            return offset
        except Exception as e:
            self.store.error("calibrate_clock", e)
            return 0.0

    def _ws_candidates(self) -> list[str]:
        """
        Order: known-delivering public endpoints FIRST, then provider endpoints.

        Verified empirically: the official public ws delivers in ~1s while Alchemy and dRPC
        connect+subscribe but never push, which silently degrades detection to the poll.
        """
        healthy = self.rpc.url or ""
        out: list[str] = []
        for u in PREFERRED_WS:
            if u not in out:
                out.append(u)
        for u in self._cand_ws:
            host = u.split("//", 1)[-1].split("/")[0]
            if host and host in healthy and u not in out:
                out.append(u)
        for u in self._cand_ws:
            if u not in out:
                out.append(u)
        if PUBLIC_WS not in out:
            out.append(PUBLIC_WS)
        return out

    def _choose_ws(self, attempt: int = 0) -> str:
        c = self._ws_candidates()
        return c[min(attempt, len(c) - 1)] if c else PUBLIC_WS

    # ------------------------------------------------------------------ state
    def _load_existing(self) -> None:
        for rec in self.store.read_signals():
            if rec.get("kind") == "signal":
                self.seen_sigs.add(rec.get("sig"))
                # v3.2: only rehydrate pending forwards for the CURRENT fingerprint.
                # track() is budget-limited (max_fetches per pass), and dict order means it
                # works the queue oldest-first. Loading every incomplete signal ever recorded
                # -- including the 3,612 belonging to the excluded v3.1 (6a9f1ff9...) and
                # legacy (d3753551...) fingerprints -- therefore starved the signals the v3.2
                # verdict will actually read, while spending the Jupiter budget (and the
                # resulting 429 storm) on data already declared unanalysable.
                # seen_sigs still absorbs every signature, so old signatures are not
                # re-ingested when the poll encounters them.
                if not rec.get("complete") and rec.get("config_fp") == self.fp:
                    self.pending[rec["id"]] = rec
            elif rec.get("kind") == "forward":
                sig = self.pending.get(rec.get("id"))
                if sig is not None:
                    sig.setdefault("forward", {})[str(rec["h"])] = rec
        self.store.note(f"loaded {len(self.seen_sigs)} prior signals, {len(self.pending)} pending")

    # ------------------------------------------------------------------ ingest
    def ingest(self, wallet: str, sig: str, detected_at: float,
               detect_slot: int | None = None, slot_source: str | None = None) -> None:
        """Fetch, parse and (if it is a qualifying buy) record a signal."""
        if not sig or sig in self.seen_sigs:
            return
        self.seen_sigs.add(sig)
        self.counters["detected"] += 1

        tx = self.rpc.get_transaction(sig)
        if tx is None:
            self.store.error("ingest", "getTransaction returned None", sig=sig, wallet=wallet)
            return

        p = parse_swap(tx, wallet, self.quote_mints)
        if not p["parse_ok"]:
            # visible, not silent: parse dropouts are counted and explained
            self.store.error("ingest.parse", p.get("reason") or "unknown", sig=sig, wallet=wallet)
            self.counters["skipped"] += 1
            return
        if p["action"] != "BUY":
            return
        # Recency gate: the poll backfills up to 4 signatures per wallet, which can be hours
        # old (the first run produced lat=35864s and lat=114703s entries). Those are not
        # copyable signals, they waste the RPC budget, and they inflate n. Drop them.
        max_age = float(self.cfg["detection"].get("max_signal_age_sec", 300))
        if p.get("block_time"):
            age = (detected_at - p["block_time"]) - self.clock_offset_sec
            if age > max_age:
                self.counters["stale_dropped"] = self.counters.get("stale_dropped", 0) + 1
                self.store.error("ingest.stale", f"dropped stale signal age={age:.0f}s",
                                 sig=sig, wallet=wallet, limit=max_age)
                return
        self.counters["buys"] += 1

        mint = p["mint"]
        sol_usd = self.prices.sol_price()
        pr = self.prices.price(mint)
        entry = pr.get("price")

        unit = float(p.get("ui_amount") or 0)
        notional = (unit * entry) if (entry and unit) else None

        # --- latency, two ways -------------------------------------------------
        tx_slot = p.get("slot")
        if slot_source is None:
            slot_source = "caller"
        if detect_slot is None and tx_slot is not None:
            # Fallback for paths that supply no reference (and for a failed per-batch
            # getSlot). Costs one RPC call per signal, hence the per-batch optimisation
            # in poll_once.
            detect_slot = self.rpc.call("getSlot", [{"commitment": "confirmed"}])
            slot_source = "per_signal"
        lat_slot = None
        if tx_slot is not None and detect_slot is not None:
            # v3.2: uses the MEASURED slot duration, not a 0.4 literal. Note this figure also
            # absorbs ingest's own processing time, because getSlot below is fetched AFTER the
            # price lookups -- so for poll-detected signals prefer latency_sec (wall), which
            # v3.2 gates on.
            lat_slot = (int(detect_slot) - int(tx_slot)) * self.slot_sec
        lat_wall = None
        if p.get("block_time"):
            lat_wall = (detected_at - p["block_time"]) - self.clock_offset_sec

        rec = {
            "kind": "signal",
            "id": f"{sig[:16]}",
            "wallet": wallet,
            "mint": mint,
            "sig": sig,
            "slot": tx_slot,
            "detect_slot": detect_slot,
            # v3.2: "batch" => detect_slot is one reference shared by a whole poll batch, so
            # latency_sec_slot is a batch-granular LOWER bound. "caller" => supplied by the
            # detector (websocket, accurate). "per_signal" => fetched individually.
            "detect_slot_source": slot_source if detect_slot is not None else None,
            "block_time": p.get("block_time"),
            "detected_at": detected_at,
            "latency_sec": lat_wall,                 # clock-corrected wall clock
            "latency_sec_slot": lat_slot,            # clock-INDEPENDENT (primary evidence)
            "clock_offset_sec": self.clock_offset_sec,
            # v3.1: A = tracked on the websocket (fast, frequency-ranked subset)
            #       B = found by poll rotation over the full universe (unbiased, slower)
            "tier": "A" if wallet in getattr(self, "_tierA", set()) else "B",
            "wallet_sol_delta": p.get("sol_delta"),
            "wallet_quote_asset": p.get("quote_asset"),
            "observed_fee_lamports": p.get("fee_lamports"),
            "tokens_ui": unit,
            "entry_price": entry,
            "entry_liq_usd": pr.get("liq_usd"),
            "price_source": pr.get("source"),
            "sol_usd": sol_usd,
            "notional_usd_est": notional,
            "config_fp": self.fp,
            "prereg_version": self.cfg.get("preregistration_version"),
            "forward": {},
            "max_price": entry,
            "min_price": entry,
            "complete": False,
        }

        if entry is None:
            rec["usable"] = False
            rec["unusable_reason"] = "no_entry_price"
            self.store.error("ingest.price", "no entry price", sig=sig, mint=mint)
            self.store.signal(rec)
            self.counters["skipped"] += 1
            return

        min_notional = float(self.cfg.get("min_buy_usd", 0))
        if notional is not None and min_notional and notional < min_notional:
            rec["usable"] = False
            rec["unusable_reason"] = f"below_min_notional({notional:.2f}<{min_notional})"
            self.store.signal(rec)
            self.counters["skipped"] += 1
            return

        # measure REAL slippage: price impact of the large size vs a $1 quote. Depth-based,
        # so it does not depend on which source supplied the mid price (the first run
        # compared a Jupiter quote to a Jupiter mid, forcing slippage to ~0 by construction).
        notional_q = float(self.cfg["friction"]["notional_usd_for_quote"])
        qt = self.prices.quote_buy_two_sizes(mint, notional_q, small_usd=1.0)
        q = {"ok": qt.get("ok"), "reason": qt.get("reason")}
        slip = qt.get("slippage_pct")
        slip_measured = bool(qt.get("ok") and slip is not None)
        if not slip_measured:
            slip = float(self.cfg["friction"]["fallback_slippage_pct_per_side"])
        rec["quote"] = {"ok": q.get("ok"), "reason": q.get("reason"),
                        "impact_pct": qt.get("impact_pct"),
                        "effective_small": qt.get("effective_small"),
                        "effective_big": qt.get("effective_big")}
        rec["slippage_pct_per_side"] = slip
        rec["slippage_measured"] = slip_measured
        rec["mid_source"] = pr.get("source")
        rec["slippage_verified"] = slip_measured   # depth-based impact is self-contained
        rec["friction_pct"] = friction_pct(
            slip, float(self.cfg["friction"]["dex_fee_pct_per_side"]),
            float(self.cfg["friction"]["assumed_gas_lamports_per_tx"]),
            sol_usd, float(self.cfg["friction"]["notional_usd_for_quote"]))
        rec["usable"] = slip_measured          # primary verdict uses measured slippage only

        self.store.signal(rec)
        self.pending[rec["id"]] = rec
        self.counters["signals"] += 1
        self.store.note(
            f"SIGNAL {mint[:8]} w={wallet[:6]} "
            f"lat={('%.1fs' % lat_slot) if lat_slot is not None else '?'}"
            f"(wall={('%.1fs' % lat_wall) if lat_wall is not None else '?'}) "
            f"notional~${notional or 0:.0f} slip={slip:.2f}% ({pr.get('source')}) "
            f"friction={rec['friction_pct']:.2f}%")

    # ------------------------------------------------------------------ tracking
    def track(self, max_fetches: int = 60) -> int:
        """Fill due forward horizons. Idempotent: each (id, horizon) written once."""
        t = time.time()
        fetches = 0
        for sid, sig in list(self.pending.items()):
            base = sig.get("detected_at")
            entry = sig.get("entry_price")
            if not base or not entry:
                sig["complete"] = True
                continue
            elapsed = t - base
            for h in self.horizons:
                key = str(h)
                if key in sig.get("forward", {}) or elapsed < h:
                    continue
                if fetches >= max_fetches:
                    return fetches
                pr = self.prices.price(sig["mint"])
                p = pr.get("price") or self.prices.price_fast(sig["mint"])
                fetches += 1
                if p is None:
                    continue
                # glitch guard: the audited system was poisoned by absurd marks, so reject
                # non-positive and absurd-upside marks. CHANGED 2026-10-11 (later session): the
                # LOWER bound (ratio < 0.005, a >99.5% collapse) is REMOVED. For a memecoin that
                # rugs, a >99.5% collapse is a REAL outcome; rejecting it deleted genuine deep
                # losses. Measured on live data: 79 distinct (signal, horizon) pairs, ALL in the
                # v3.2 fingerprint, at h=3600 (22) and h=14400 (57), 44 of which never got any
                # fill at all -- so the long-horizon distribution was biased upward. v1 was
                # untouched (0 pairs), so every published v1 number stands.
                ratio = p / entry
                if not (isinstance(p, (int, float)) and p > 0) or ratio > 100.0:
                    # `continue` used to leave the horizon unfilled, so every 20s pass retried
                    # and re-logged it forever: 19,297 track.glitch lines for those 79 pairs, a
                    # large share of a 38MB errors.jsonl. Log it once per (id, h) per process.
                    logged = getattr(self, "_glitch_logged", None)
                    if logged is None:
                        logged = self._glitch_logged = set()
                    if (sid, h) not in logged:
                        logged.add((sid, h))
                        self.store.error("track.glitch", f"implausible price ratio {ratio:.4g}",
                                         id=sid, h=h, price=p, entry=entry, mint=sig["mint"])
                    continue
                gross = (p / entry - 1.0) * 100.0
                net = gross - float(sig.get("friction_pct") or 0.0)
                # track_policy marks the 2026-10-11 admissibility change. The config fingerprint
                # is a hash of CONFIG and therefore CANNOT move for a code change; without this
                # key, records from either side of the change would be silently pooled. Records
                # written before this change carry no such key.
                rec = {"kind": "forward", "id": sid, "h": h, "price": p,
                       "age_sec": round(elapsed, 1), "gross_pct": round(gross, 4),
                       "net_pct": round(net, 4),
                       "track_policy": "keep_deep_losses_20261011", "ts": now_iso()}
                self.store.signal(rec)
                sig.setdefault("forward", {})[key] = rec
                if p > (sig.get("max_price") or 0):
                    sig["max_price"] = p
                if p < (sig.get("min_price") or entry):
                    sig["min_price"] = p
                self.counters["forward"] += 1
                self.store.note(f"  fwd {sid} +{h}s gross={gross:+.2f}% net={net:+.2f}%")
            if elapsed > max(self.horizons) + 300:
                sig["complete"] = True
                self.store.signal({"kind": "complete", "id": sid,
                                   "max_price": sig.get("max_price"),
                                   "min_price": sig.get("min_price"),
                                   "ts": now_iso()})
                self.pending.pop(sid, None)
        return fetches

    # ------------------------------------------------------------------ detection
    def poll_once(self, offset: int = 0) -> int:
        """Rotating poll over the Tier B universe."""
        if not self.cfg["detection"].get("poll_fallback_enabled", True):
            return offset
        batch = int(self.cfg.get("poll_rotation_batch", 12))
        n = len(self.poll_wallets)
        if n == 0:
            return offset

        # ---- v3.2: enforce the recency allowance BEFORE spending RPC -------------------
        # getSignaturesForAddress already returns blockTime for every entry, so checking
        # recency here costs nothing extra. The age check used to live inside ingest(), i.e.
        # AFTER get_transaction() had been paid for -- so every out-of-allowance signature
        # still cost a full getTransaction (plus the getSlot that ingest issues when
        # detect_slot is None), and the then-180s gate silently discarded 59% of Tier B
        # while discarding 0% of Tier A, steering the test onto the frequency-ranked tier.
        max_age = float(self.cfg["detection"].get("max_signal_age_sec", 300))
        limit = int(self.cfg["detection"].get("poll_sig_limit", 4))
        # v3.2: ONE getSlot per batch instead of one per signal. ingest used to call getSlot
        # for every poll-detected signal (detect_slot is None on this path) -- 64 of the 342
        # RPC calls in the first v3.2 window, every one of them a blocking round-trip, purely
        # to populate the slot-latency diagnostic. v3.2 gates on WALL latency, so a single
        # per-batch reference is sufficient. Records are flagged detect_slot_source="batch" so
        # no later analysis mistakes this batch-granular lower bound for a per-signal reading.
        batch_slot = self.rpc.call("getSlot", [{"commitment": "confirmed"}])
        picks = [self.poll_wallets[(offset + i) % n] for i in range(min(batch, n))]
        for w in picks:
            sigs = self.rpc.get_signatures(w, limit=limit)
            if not sigs:
                continue
            for s in sigs:
                if s.get("err"):
                    continue
                sig = s.get("signature")
                bt = s.get("blockTime")
                if sig and bt and sig not in self.seen_sigs:
                    age = (time.time() - float(bt)) - self.clock_offset_sec
                    if age > max_age:
                        if sig not in self._stale_sigs:
                            self._stale_sigs.add(sig)
                            self.counters["stale_dropped"] = \
                                self.counters.get("stale_dropped", 0) + 1
                            self.store.error(
                                "ingest.stale",
                                f"skipped stale signal age={age:.0f}s (no RPC spent)",
                                sig=sig, wallet=w, limit=max_age)
                        continue
                self.ingest(w, sig, time.time(), detect_slot=batch_slot,
                            slot_source="batch" if batch_slot else None)
        return (offset + batch) % n

    async def ws_loop(self) -> None:
        import websockets
        backoff = 1.0
        failures = 0
        while True:
            try:
                self.ws_url = self._choose_ws(failures)
                self.store.note(f"ws connecting ({len(self.wallets)} wallets) -> {redact_text(self.ws_url)}")
                async with websockets.connect(self.ws_url, ping_interval=20,
                                              max_size=2 ** 22, open_timeout=20) as ws:
                    sub_to_wallet: dict[int, str] = {}
                    req_to_wallet: dict[int, str] = {}
                    for i, w in enumerate(self.wallets, start=1):
                        req_to_wallet[i] = w
                        await ws.send(json.dumps({
                            "jsonrpc": "2.0", "id": i, "method": "logsSubscribe",
                            "params": [{"mentions": [w]}, {"commitment": "confirmed"}]}))
                    self.store.note(f"ws subscribed on {redact_text(self.ws_url)}; listening")
                    backoff = 1.0
                    failures = 0
                    notifs_at_connect = self.counters.get("ws_notifications", 0)
                    silent_deadline = time.time() + WS_SILENCE_TIMEOUT_SEC
                    # explicit recv with timeout so a CONNECTED BUT SILENT endpoint can be
                    # detected and swapped out, instead of quietly leaving the poll to work
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(),
                                                         timeout=max(1.0, silent_deadline - time.time()))
                        except asyncio.TimeoutError:
                            now_n = self.counters.get("ws_notifications", 0)
                            if now_n <= notifs_at_connect:
                                self.store.note(
                                    f"WS SILENT: {redact_text(self.ws_url)} delivered 0 notifications "
                                    f"in {WS_SILENCE_TIMEOUT_SEC:.0f}s - rotating to next endpoint "
                                    f"(detection was falling back to the {self.cfg['detection']['poll_interval_sec']:.0f}s poll)")
                                failures += 1
                                break
                            silent_deadline = time.time() + WS_SILENCE_TIMEOUT_SEC
                            continue
                        got = time.time()
                        try:
                            d = json.loads(raw)
                        except Exception as e:
                            self.store.error("ws.json", e, raw=str(raw)[:160]); continue
                        if "id" in d and "result" in d and isinstance(d["result"], int):
                            w = req_to_wallet.get(d["id"])
                            if w:
                                sub_to_wallet[d["result"]] = w
                            continue
                        if "id" in d and d.get("error"):
                            # a silently-failing subscription is why the ws can look "connected"
                            # while delivering nothing and the slow poll does all the work
                            self.store.error("ws.subscribe_failed", str(d.get("error"))[:200],
                                             id=d.get("id"),
                                             wallet=str(req_to_wallet.get(d.get("id")))[:12])
                            continue
                        if d.get("method") != "logsNotification":
                            continue
                        self.counters["ws_notifications"] = self.counters.get("ws_notifications", 0) + 1
                        prm = d.get("params") or {}
                        val = (prm.get("result") or {}).get("value") or {}
                        if val.get("err"):
                            continue
                        sig = val.get("signature")
                        w = sub_to_wallet.get(prm.get("subscription"))
                        slot = (prm.get("result") or {}).get("context", {}).get("slot")
                        if sig and w:
                            self.ingest(w, sig, got, detect_slot=slot)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.store.error("ws.loop", e)
                failures += 1
                self.store.note(
                    f"ws error ({type(e).__name__}) attempt {failures}; "
                    f"next={redact_text(self._choose_ws(failures))} backoff {backoff:.0f}s")
                if failures == 3:
                    self.store.note("WARNING: websocket failing repeatedly - detection is falling "
                                    "back to the poll, which is slower. Check the ws provider.")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def track_loop(self, every: float = 20.0) -> None:
        last_cal = time.time()
        while True:
            try:
                self.track()
                # The clock may be free-running (Windows Time service disabled), so the
                # wall-clock correction goes stale. Re-calibrate periodically so the rig
                # never depends on the host clock being right. Slot-based latency is
                # already immune; this keeps the secondary wall-clock figure honest too.
                if time.time() - last_cal > 1800:
                    self.clock_offset_sec = self._calibrate_clock()
                    last_cal = time.time()
            except Exception as e:
                self.store.error("track_loop", e)
            await asyncio.sleep(every)

    async def poll_loop(self, offset: int = 0) -> None:
        interval = float(self.cfg["detection"].get("poll_interval_sec", 3.0))
        while True:
            try:
                offset = self.poll_once(offset)
                self.store.note(
                    f"poll offset={offset} rpc_today={self.rpc.calls_today}/{self.rpc.max} "
                    f"signals={self.counters['signals']} forwards={self.counters['forward']} "
                    f"ws_notifs={self.counters.get('ws_notifications', 0)} "
                    f"stale_dropped={self.counters.get('stale_dropped', 0)} "
                    f"429s={self.rpc.rate_limit_hits}")
            except Exception as e:
                self.store.error("poll_loop", e)
            await asyncio.sleep(max(1.0, interval))

    async def run_forever(self) -> None:
        tasks = [asyncio.create_task(self.track_loop())]
        tasks.append(asyncio.create_task(self.poll_loop()))
        if self.cfg["detection"].get("use_websocket", True):
            tasks.append(asyncio.create_task(self.ws_loop()))
        await asyncio.gather(*tasks)


# ------------------------------------------------------------------------------ modes
def _recorded_buys(limit: int = 12) -> list[dict]:
    """Real memecoin BUY events from Legion's own ledger, for parser cross-checking."""
    src = r"C:\LEGION\wallet_events.json"
    try:
        with open(src, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return []
    evs = d.get("events", d) if isinstance(d, dict) else d
    return [e for e in evs
            if e.get("action") == "BUY" and e.get("signature") and e.get("token_mint")][:limit]


def _crosscheck_parser(rig: "Rig", cfg: dict, limit: int = 6, quiet: bool = False) -> tuple[int, int]:
    """Parse real recorded BUY events and compare against the recorded action+mint."""
    agree = disagree = failed = 0
    for e in _recorded_buys(limit):
        sig, wallet, mint = e["signature"], e["wallet"], e["token_mint"]
        tx = rig.rpc.get_transaction(sig)
        if tx is None:
            failed += 1
            if not quiet:
                print(f"  {sig[:12]}  FETCH FAILED")
            continue
        p = parse_swap(tx, wallet, cfg["quote_mints"])
        if p.get("parse_ok") and p.get("action") == "BUY" and p.get("mint") == mint:
            agree += 1
            if not quiet:
                print(f"  {sig[:12]}  OK        mint={mint[:10]} tokens={p.get('ui_amount')}")
        else:
            disagree += 1
            if not quiet:
                print(f"  {sig[:12]}  MISMATCH  parsed={p.get('action')}/{str(p.get('mint'))[:10]} "
                      f"expected=BUY/{mint[:10]}  reason={p.get('reason')}")
    return agree, agree + disagree


def cmd_selftest() -> int:
    print("=" * 78); print("KILL TEST — SELF TEST"); print("=" * 78)
    hits = selfcheck()
    cfg = load_config()
    store = Store(os.path.join(HERE, cfg.get("log_dir", "logs")))
    print(f"config fingerprint: {config_fingerprint(cfg)}")
    rig = Rig(cfg)
    print(f"cred source: {rig.cred_source}")
    print(f"rpc url: {redact_text(rig.rpc_url)}")
    print(f"ws  url: {redact_text(rig.ws_url)}")
    if rig.creds.get("refused"):
        print(f"REFUSED fields (looked like key material): {rig.creds['refused']}")
    if rig.creds.get("error"):
        print(f"config note: {rig.creds['error']}")
    print(f"wallets loaded: {len(rig.wallets)}")
    print(f"horizons: {rig.horizons}  primary={cfg['primary_horizon_sec']}s  min_n={cfg['min_n_for_verdict']}")
    sol = rig.prices.sol_price()
    print(f"live SOL price: {sol}")
    # live price path
    test_mint = WSOL
    pr = rig.prices.price(test_mint)
    print(f"price({test_mint[:8]}): {pr}")
    # live swap-parse path, cross-checked against Legion's own recorded memecoin buys
    print("\nparser cross-check on real recorded BUY events (Agreement = parser is correct):")
    agree, total = _crosscheck_parser(rig, cfg, limit=6)
    print(f"\nparser agreement: {agree}/{total}"
          f"{f' ({agree/total*100:.0f}%)' if total else ''}")
    print("self-check hits:", hits if hits else "none")
    ok = (not hits) and total > 0 and agree / total >= 0.8
    print("\nSELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_import(sig: str, wallet: str) -> int:
    cfg = load_config()
    rig = Rig(cfg)
    rig.ingest(wallet, sig, time.time())
    rig.track()
    print(f"counters: {rig.counters}")
    return 0


def cmd_verifyparse(limit: int = 12) -> int:
    """
    Cross-check the swap parser against Legion's OWN recorded wallet events.
    If the parser agrees with the recorded action+mint, it works.
    """
    cfg = load_config()
    rig = Rig(cfg)
    print(f"recorded BUY events available: {len(_recorded_buys(10000))}")
    agree, total = _crosscheck_parser(rig, cfg, limit=limit)
    print(f"\nparser agreement: {agree}/{total}"
          f"{f' ({agree/total*100:.0f}%)' if total else ''}")
    return 0 if (total and agree / total >= 0.8) else 1


def cmd_creds() -> int:
    """Show which endpoint the rig would use, and prove no key material was read."""
    cfg = load_config()
    c = load_rpc_credentials(cfg.get("legion_config_path"))
    print("=" * 84); print("KILL TEST — CREDENTIAL RESOLUTION (values masked)"); print("=" * 84)
    print(f"config path        : {c.get('path')}")
    print(f"read error         : {c.get('error') or 'none'}")
    print(f"allowlisted found  : {c['found'] or 'none'}")
    print(f"refused (key-like) : {c['refused'] or 'none'}")
    print(f"rpc candidates     : {[redact_text(u) for u in c['rpc_urls']] or 'none'}")
    print(f"ws candidates      : {[redact_text(u) for u in c['ws_urls']] or 'none'}")
    if not c["rpc_urls"]:
        print("\nno allowlisted RPC field found. Field names present in that config")
        print("(NAMES ONLY — no values are read or printed):")
        for n in c["available"]:
            flag = "  <-- looks like key material, will never be read" if any(
                h in n.lower() for h in FORBIDDEN_HINTS) else ""
            print(f"   {n}{flag}")
        print("\nAdd the correct dotted path to CRED_ALLOWLIST in kt_lib.py if it is missing.")
    return 0


def cmd_status() -> int:
    cfg = load_config()
    rig = Rig(cfg)
    sigs = [s for s in rig.store.read_signals() if s.get("kind") == "signal"]
    usable = [s for s in sigs if s.get("usable")]
    lat = [s["latency_sec"] for s in usable if s.get("latency_sec") is not None]
    print(f"signals: {len(sigs)}  usable(measured slip): {len(usable)}  pending: {len(rig.pending)}")
    if lat:
        lat.sort()
        print(f"latency sec: min={lat[0]:.1f} median={lat[len(lat)//2]:.1f} max={lat[-1]:.1f}")
    print(f"rpc calls today: {rig.rpc.calls_today}/{rig.rpc.max}")
    errs = 0
    if os.path.exists(rig.store.errors):
        with open(rig.store.errors, encoding="utf-8") as f:
            errs = sum(1 for _ in f)
    print(f"errors logged: {errs}  (see logs/errors.jsonl)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__); return 2
    cmd = argv[1].lower()
    if cmd == "selftest":
        return cmd_selftest()
    if cmd == "import" and len(argv) >= 4:
        return cmd_import(argv[2], argv[3])
    if cmd == "verifyparse":
        return cmd_verifyparse(int(argv[2]) if len(argv) > 2 else 12)
    if cmd == "status":
        return cmd_status()
    if cmd in ("creds", "credentials"):
        return cmd_creds()
    if cmd in ("run", "track"):
        cfg = load_config()
        hits = selfcheck(verbose=False)
        if hits:
            print("REFUSING TO RUN: signing/order tokens found:")
            for h in hits:
                print("   ", h)
            return 1
        rig = Rig(cfg)
        if cmd == "track":
            n = rig.track(max_fetches=10000); print(f"forward fills: {n}"); return 0
        print(f"kill test running. {len(rig.wallets)} wallets, paper only, no keys.")
        try:
            asyncio.run(rig.run_forever())
        except KeyboardInterrupt:
            print("\nstopped by user")
        return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
