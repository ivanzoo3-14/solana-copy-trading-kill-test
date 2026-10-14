# KILL TEST — a clean, paper-only rig that tries to falsify the copy-trading thesis

**This rig cannot trade.** It holds no keys, signs nothing, and places no orders — and it
*verifies* that claim at startup by scanning its own source for signing/order tokens and
refusing to run if any appear.

## Why it exists

The Legion copy-trading system was measured and found dead:

- median forward return after a cluster signal (n=2,380): **−8.2%** at 1h, **−62.7%** at 24h
- median *best* excursion ever reached after a signal: **+0.56%**
- median forward max multiple (n=833 mints): **1.119×** against ~12.5% round-trip friction
- **clairvoyance bound** (buy every signal, sell at its exact peak, pay friction): median **−0.62%**
- detection latency: median **70.75 min**

But every one of those measurements was taken on the *cluster* signal — ≥3 wallets inside a
2-hour window, detected ~70 minutes late. **The single-wallet, seconds-latency variant was never
tested.** This rig tests it, once, with a pre-registered pass mark, and then stops.

Read `PREREGISTRATION.md` first. It is the contract: hypothesis, pass criterion, kill criterion,
and the no-tuning rule.

## Install / run

Requires a Python with `requests` and `websockets` (the existing LEGION venv has both).

```
run_killtest.bat selftest     # safety self-check + live parse of a real mainnet tx
run_killtest.bat run          # start detecting + forward-tracking
run_killtest.bat status       # counters, latency, RPC spend
run_killtest.bat track        # catch-up pass for due forward horizons
run_killtest.bat verdict      # apply the pre-registered criteria
```

Set a paid RPC for genuine low latency (optional but recommended):

```
set KILLTEST_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
set KILLTEST_WS_URL=wss://mainnet.helius-rpc.com/?api-key=YOUR_KEY
```

With no env vars it falls back to the public endpoint — it will still work but with more
latency and rate limits. **No key or secret is stored in this directory.**

## What it measures

For every **BUY** by a watched wallet:

| Field | Purpose |
|---|---|
| `latency_sec` | `detected_at − block_time`. **The variable under test.** Legion was ~4,245s; this should be single-digit seconds. |
| `entry_price` | mid price at detection (DexScreener deepest pool for that mint, Jupiter fallback) |
| `slippage_pct_per_side` | **measured** from a live Jupiter quote for a $50 notional vs mid — plus `priceImpactPct` |
| `friction_pct` | `2×(dex_fee + slippage) + gas`, with gas from **105,000 lamports observed on-chain**, not the $0.001 the old model used |
| `forward[30..86400]` | price at each horizon, `gross_pct`, and `net_pct` after friction |
| `max_price` / `min_price` | for the clairvoyance bound |

Forward tracking is idempotent and append-only: the log is a stream of `signal`, `forward` and
`complete` events, and the verdict script folds it. Nothing is overwritten.

## Credentials — read from your Legion config, safely

The rig reads endpoints from `legion_config_path` in `config.json` (default
`C:\LEGION\config.json`), so you don't have to duplicate keys or set env vars.

**It reads ONLY an allowlist of RPC fields** (`kt_lib.CRED_ALLOWLIST`):
`solana.helius_api_key`, `rpc.getblock_url`, `rpc.getblock_key`, `rpc.alchemy_key`.
The private key and seed phrase sitting in that same file are **never read, never returned and
never logged**. Two independent safeguards:

1. **Allowlist only** — the loader never scans for "keys"; it looks up specific dotted paths.
2. **Redaction at the log boundary** — every value loaded is registered as a secret, and all
   log/stdout output is masked, so a key cannot reach disk even if `requests` echoes a URL back
   inside an exception. Verified: a leak audit found neither key in any rig file or log.

Anything that *looks* like key material (>60 chars, or containing spaces) is **refused** and
reported, never used. Run `run_killtest.bat creds` to see exactly what it resolved, masked.

## Endpoint failover (why this matters)

On first run the rig probes each candidate with a **real `getTransaction`**, and only adopts one
that **returns data**. This is deliberate: a provider that answers HTTP 200 with a `null` result
is worse than one that is down, because it fails silently. That exact failure mode existed in the
audited Legion pipeline.

Measured on this machine at build time:

| Endpoint | Result |
|---|---|
| Helius | **429 rate limited** (the account burned ~98.6% of its quota historically) |
| GetBlock | **timeouts, and "healthy but empty"** — 200 with null results |
| **Alchemy** | **works** — selected |
| public mainnet | works — fallback |

The rig auto-selects a working endpoint and **rotates on failure during operation**, re-pointing
its websocket to match, with a polling backstop if the websocket never connects. If you top up
Helius, it will simply be picked again.

## Design rules (deliberate contrasts with the audited system)

1. **No silent failures.** Every exception goes to `logs/errors.jsonl` with context. Parse
   dropouts are *counted and explained*, and the dropout rate is printed in the verdict —
   the old pipeline's silent `except: pass` blocks are how it lied to itself.
2. **No look-ahead.** Prices are only ever read forward from `detected_at`.
3. **Append-only + atomic.** JSONL for events; `os.replace` for any JSON.
4. **Budgeted.** Hard daily RPC cap, logged per call; the poll backstop is credit-aware.
5. **Per-wallet scoreboard.** If any wallet has genuine timing skill, this finds it by
   wallet rather than hiding it in an average.
6. **Frozen parameters.** `config_fingerprint` is stamped on every signal, so signals
   collected under different settings can never be silently pooled.

## Honest limitations

- **Max excursion is sampled at discrete horizons** (30s/1m/5m/15m/1h/4h/24h), so the
  clairvoyance bound is a *lower* bound on the true peak. This makes the test slightly
  generous toward the thesis — stated so you can see the direction of the bias.
- The Jupiter quote used for slippage assumes 6 decimals for the output mint; pump.fun-style
  mints are 6dp, but exotic mints would misprice. `priceImpactPct` is recorded separately
  as a cross-check.
- Token discovery is inherited from Legion's `tracked_wallets.json`. If those wallets are
  simply unskilled, this test will find that — which is itself the answer.
- **Passing does not mean profitable.** It means the thesis survived a kill attempt. At $52,
  account size remains a separate and larger problem.

## If it passes

Do not immediately trade it. In order: more signals, out-of-sample period, capacity and
slippage at real size, then a separate decision about capital. The whole point of writing the
criterion down first is that you cannot move the goalposts afterwards.
