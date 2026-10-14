# A pre-registered kill test for Solana wallet copy-trading

**The premise failed. The instrument that proved it is here, and it is reusable.**

This repository is a measurement harness for Solana trading strategies. It ingests wallet activity
from the chain, prices it honestly, and scores a strategy against a criterion that was **frozen
before the data was collected**. Its first result was negative, and that result is included in full —
along with every correction made to it, and the four defects found in the instrument itself.

- **Flagship document:** [`docs/KILL_TEST_WRITEUP.md`](docs/KILL_TEST_WRITEUP.md)
- **Short summary with the numbers:** [`docs/WORK_SAMPLE.md`](docs/WORK_SAMPLE.md)
- **The frozen design:** [`rig/PREREGISTRATION_v3.md`](rig/PREREGISTRATION_v3.md)

## The headline result

| measurement | value |
|---|---|
| Pre-registered verdict (median net at 5 min, n=357) | **−2.51%**, 40.1% positive, one-way sign test **p = 0.9999** |
| Perfect-exit ceiling, all horizons | **+10.17%** median — but a **≥900 s** phenomenon, not a fast one |
| Perfect-exit ceiling, first 30–120 s | **−0.78%** (gross **+0.00%**); age-clean 300 s **−0.97%** |
| Take-profit / stop / timeout rules (60 coarse + 96 fine) | **all negative**; best −1.07% |
| Depth-based friction, $1 vs $50 against an independent mid | median **0.40% per side / 1.46% round trip** |

Two findings are the point of the exercise:

1. **The median signal's best price in its first two minutes is its first observed price.** In 62–72%
   of paths nothing later exceeds the first sample by even 0.5 pp. There is no fast pop to capture.
2. **The upside that does exist lives in a fat tail hours out**, and every consistent exit rule
   truncates exactly that tail. Detection was already at same-slot latency, so "be faster" was not
   available either.

## Why this is worth reading even though the strategy lost

Most strategy results are unfalsifiable and never mention their own errors. This one carries a
**dated correction log**: a glitch guard that silently deleted the deepest losses; a bar labelled
"+30 s" that was fetched at a median age of 87 s and *flattered* the result; a published friction
figure that could not be reproduced from the data; and a restart path that re-queued the entire
history. A 30-invariant data-quality audit found 12 failing, each attributed, fixed or explained.

## Layout

```
rig/                 the harness: ingestion, pricing, friction, pre-registration enforcement, verdicts
  kt_lib.py          stores, RPC with budget+failover, depth-based prices, friction model
  kt_run.py          detector + tracker (websocket logsSubscribe with a polling backstop)
  kt_verdict.py      the pre-registered v1 verdict and the clairvoyance bound
  kt_wallets.py      the v3 out-of-sample wallet-selection verdict
  kt_fastpath.py     120 s dense price paths (the sub-minute question)
  ktctl.py           start/stop/status for the two services
docs/                the writeup and the one-page work sample
tools/               probes that re-derive the published numbers from the rig's own logs
  short_ceiling.py   the short-horizon ceiling; reproduces the published v1 table to the digit
  data_quality_audit.py, audit_sensitivity.py, robustness_checks.py, noinfo_final.py
tools/legion-coupled/  probes that read a separate private system's data (see the note inside)
```

## Safety and scope

- **Paper only by construction.** The harness holds no keys, signs nothing, and places no orders. It
  is a measurement tool, not a trading system.
- **No credentials in this repo.** `rig/config.example.json` is a template; the real config is
  gitignored. The rig reads only RPC endpoint credentials, never a wallet key.
- **Not investment advice.** Nothing here claims or implies a profitable strategy.

## Reproducing

The rig is portable; the audit probes in `tools/` were written against the author's absolute layout
(`C:\killtest-rig`, `C:\LEGION`) and need those constants pointed at your paths — the limitation is
called out at the top of each file and is slated for the first release cleanup.

```
python rig/kt_verdict.py      # the pre-registered verdict + clairvoyance bound
python rig/kt_wallets.py      # the v3 holdout verdict (inconclusive while collecting)
python tools/short_ceiling.py # the short-horizon ceiling, verified against the rig's own fold()
```

## License

MIT — see [`LICENSE`](LICENSE).
