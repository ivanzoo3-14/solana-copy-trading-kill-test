# Work sample — a pre-registered test of Solana wallet copy-trading

**One line:** I spent seven months building a Solana copy-trading bot, then built a separate rig to
test whether its premise was *true* instead of tuning it. The premise failed, and I wrote up the
negative result — including every place my own measurement was wrong and had to be corrected.

*Status: written up in full and ready to publish; the full document and all probes are local until
my key rotation is done (see "Reproduction").*

## The result, in numbers

| measurement | value |
|---|---|
| Pre-registered verdict (median net, 5 min, n=357) | **−2.51%**, 40.1% positive, one-sided sign test **p = 0.9999** |
| Perfect-exit ceiling, all horizons | median **+10.17%** (CI [+7.27, +13.89]), 70.3% positive — but a **≥900 s** phenomenon |
| Perfect-exit ceiling, first 30–300 s | **−0.78%** at 30 s (gross **+0.00%**), ≈0% at 300 s; age-clean 300 s **−0.97%** |
| Take-profit / stop / timeout rules (60 coarse + 96 fine) | **all negative**; best −1.07% coarse, −0.98% fine |
| Entry timing (matched-holding control) | median paired difference **exactly 0**, 54% ties |
| Clustered inference | by wallet (15 clusters): SE ×1.78, CI [−5.36%, −0.39%]; by mint (192): ×1.07, CI [−4.35%, −1.15%] |
| Power | could detect a 56.6% positive rate vs a 50% null; observed 40.1% (mean MDE ±8.90 pp) |
| Friction (depth-based, $1 vs $50 vs an independent mid) | median **0.40% per side / 1.46% round trip** (the mean is unusable — extreme tail) |
| Micro-cap decay (the system's own tracker) | median −9.7% (1 h), −36.5% (6 h), −62.5% (24 h), −86.9% (7 d), against a +699% mean at 1 h |

**The shape of the failure:** the median signal's best price in its first two minutes *is its first
observed price*. The upside that exists lives in a fat right tail hours out, and every consistent exit
rule truncates exactly that tail. Detection was already at same-slot latency, so "be faster" was not
available either.

## What I built

- **Detection:** websocket `logsSubscribe` with per-wallet mention filters plus a polling backstop,
  reaching **0.0 s / same-slot** detection. Latency derived **clock-independently from slot numbers**
  (measured 0.218–0.225 s/slot from `block_time`/`slot` pairs, after host clock drift corrupted the
  wall-clock measure).
- **Honest cost measurement:** depth-based price impact across two notionals against an independent
  mid, replacing a circular quote-vs-mid estimate that forces ~0% by construction.
- **Pre-registration enforcement:** frozen hypothesis, pass/kill criterion, minimum n, and a
  **config-fingerprint** that refuses to pool data collected under different criteria sets.
- **Verdict tooling:** sign tests, cluster bootstraps, power/MDE, a clairvoyance bound, and a
  no-information control — plus a data-quality audit that runs invariants over the raw logs.
- **A live experiment** testing whether wallet *selection* carries out-of-sample information
  (60/40 time split, criterion frozen before collection; currently inconclusive and still collecting).

## Why this is worth reading (the part I'd actually hire for)

Most strategy writeups are unfalsifiable, and most never mention their own errors. This one has a
**dated correction log**, and the corrections were found by re-deriving my own published numbers:

- A **glitch guard** in the forward tracker was silently deleting the deepest losses for one
  configuration — biasing long-horizon results upward (79 affected pairs, measured).
- A bar labelled **"+30 s" was being fetched at a median age of 87 s**; scoring late bars *flattered*
  results. Restoring an age-clean sample moved the 300 s ceiling from +0.17% to **−0.97%**.
- A published **friction figure ("~1.05–1.13% per side") could not be reproduced from the data** by
  any summary statistic. It was corrected to the measured 0.40%/side in six files.
- Restarting the collector **re-queued the entire history** (4,189 signals), starving new signals and
  driving provider rate limits — root-caused to a `complete` flag that was never persisted.
- A restart control was **anchor-sensitive**: shifting the anchor one sample turned a confident
  "+2.56 pp, CI excludes zero" into +0.00 pp with 54% ties. The original "effect" was an artefact.
- A no-information benchmark was **withdrawn** because its metric was defined nowhere in the code and
  could not be reproduced — a figure nobody can re-derive doesn't belong in the document.
- Published figures were re-derived at the final n (they had been quoted at n≈166 and gone stale),
  and a slot-duration constant was measured rather than assumed (0.4 s → 0.218–0.225 s).

A 30-invariant data-quality audit was run over the raw logs: **12 failed**, each attributed and
fixed or explained, and a sensitivity analysis confirmed the headline result under every repair
(duplicate fills resolved the other way: −0.046 pp; flagged signals dropped entirely: +0.027 pp).

## What it does not show

One asset class (Solana micro-cap launchpad tokens), one wallet universe, a few thousand signals.
The findings bound that sample. The rig is a measurement instrument, not a trading system: it holds
no keys, signs nothing, and refuses to start if any signing path exists in the codebase. Nothing here
is investment advice, and no positive-expectancy strategy is claimed or implied.

## Reproduction

Self-contained Python, paper-only, no credentials required to re-run the analysis:

```
python kt_verdict.py        # the pre-registered verdict + clairvoyance bound
python kt_wallets.py        # the wallet-selection holdout verdict
python short_ceiling.py     # the short-horizon ceiling; reproduces the published v1 table to the digit
python data_quality_audit.py, audit_sensitivity.py, robustness_checks.py   # the audit trail
```

## Contact

- GitHub: `<your-handle>` · X: `<your-handle>` · Email: `<you@example.com>`
- Full writeup, probe scripts and frozen pre-registration available on request (or at `<repo-url>`
  once the key rotation is complete).
