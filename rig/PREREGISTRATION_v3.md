# PREREGISTRATION v3 — Out-of-sample wallet selection

**Frozen before any data collection for this test. Do not edit after collection begins.**

Version 1 tested the copy-trade premise and killed it. This tests a narrower, different
question that v1 left open: **is the failure in the signals, or only in wallet selection?**

v1 evidence motivating this:
- Payoff was negative at every horizon for the pooled wallet set.
- But per-wallet dispersion was real: best `+4.35%` (n=47, p=0.07) to worst `−7.50%` (n=93).
- The **most active** wallet was the **worst**, and the best was the **second-least active** —
  consistent with frequency-ranked selection recruiting market makers rather than skill.

> **NOTE ADDED 2026-10-11 — half of the bullet above does not survive the larger sample.**
> Recomputed on the final v1 data (primary pool n=357, wallets with n≥10), seven wallets qualify:
>
> | wallet | n | median net 5 min |
> |---|---|---|
> | `8zkgFGVZ…` | 47 | **+4.35%** |
> | `922M9fBT…` | 44 | −1.65% |
> | `F6pq4Unx…` | 41 | −2.22% |
> | `3K7XMbqv…` | 52 | −2.82% |
> | `nQEqsdvA…` | 51 | −3.76% |
> | `13VK7ZrR…` | 16 | −6.52% |
> | `HGXr65Ki…` | 93 | **−7.50%** |
>
> **Holds:** the most active wallet is the worst (n=93, −7.50%). ✓
> **Fails:** the best (n=47) is *mid-pack* by activity, not second-least active; and the least active
> wallet (n=16) is one of the worst. The "best wallets are inactive" reading was an artefact of a
> ~n=20 sample. Six of seven are net negative, and only one is positive.
> **Consequence for this document's reasoning:** "frequency-ranked selection recruits bots/market
> makers" is still supported by the most-active-is-worst fact. The stronger claim — that skill hides
> in *inactivity* — is **not** supported, and should not be used to argue that a low-frequency wallet
> screen would have found the edge. **No test parameter changes.**
- Every fixed take-profit/stop rule lost money, but *uncapped hold* had a positive mean
  (+2.69% at 900s). So the exit problem is downstream: with a positive-median signal, holding works.

> **NOTE ADDED 2026-10-11 — the last bullet above is stale. The frozen text is left unaltered as
> the record of what was believed when v3 was registered, but it must not be quoted as fact.**
> The "+2.69% at 900s" figure was taken from an early, smaller dataset. Recomputed on the final v1
> data (`kt_sweep.py`, v1 fingerprint, n=456): uncapped hold at 900 s has mean **−0.16%**, median
> **−4.69%**, win rate **36.6%** — i.e. **zero, not positive**.
> **Consequence for this document's reasoning:** the inference "*with a positive-median signal,
> holding works, therefore the exit problem is downstream*" does **not** follow. The 900 s median is
> itself −4.69%. So v3 is not licensed to assume the signals are sound and only the exits are
> broken — which is precisely the assumption H1 is designed to test rather than presuppose.
> **What this does NOT change:** H1, the pass criterion, the kill criterion, K, the horizon, the
> split, the stopping rule, or the prior. H1 was always framed as a live question, and it stays one.
> It was also never robust at the original figure: the +0.23%–+2.69% range rested on ~10 signals,
> and excluding the top 10 the 900 s mean is −7.5%.

## H1 (single hypothesis)

A wallet subset selected **only** on a training period will show **positive net
forward-return expectancy on a later, held-out period**, after measured friction.

If H1 fails, no wallet tracker can rescue this premise, and the line of work closes.

## Universe

Wallets drawn from all available discovery sources, unioned and deduplicated:
- Legion `wallet_events.json` (observed BUY activity)
- Legion's discovery output, if present
- The v1 frozen list

Selection for the universe is by **observed activity only** — never by returns. Any wallet
with ≥1 observed BUY is eligible. This is deliberate: choosing which wallets to *observe* is
not the hypothesis. Choosing which to *follow* is, and that happens in the training step.

## Data

Per signal: wallet, mint, entry price, **slot-based latency**, `usable` (measured slippage,
notional ≥ $50), `friction_pct`, and net forward returns at 30/60/300/900/3600 s.

Unchanged from v1: first-per-(wallet, mint) dedup; config fingerprint must match; entry price
required; notional floor respected. Primary horizon remains **300 s**.

## Train / holdout split — the core of the design

Split by **time**, not at random:

- **Training window** = the first 60% of collection, by signal `detected_at`
- **Holdout window** = the final 40%
- The boundary timestamp is recorded when the split is made and never moved.

Ranking on the training window and evaluating on a later window is the entire point. A random
split would leak: the same mint's move appears on both sides.

## Selection rule (training only)

For each wallet with **n ≥ 25 usable training signals**:
- score = **median net return at 300 s**

Take the **top K = 5** wallets by that score. If fewer than 5 wallets have n ≥ 25, take the
top 3 and note reduced power. No other filters. No manual exclusions.

## Pass criterion

Evaluated on the **holdout only**, for the signals from the K selected wallets:

1. **n ≥ 100** usable holdout signals across the K wallets, and
2. **median net 300 s return > 0**, and
3. **one-sided sign test p < 0.05** (fraction of holdout signals with net > 0 exceeds 50%)

All three required. Any failure is a kill.

## Kill criterion

- median net 300 s ≤ 0 on holdout, **or**
- sign test p ≥ 0.05, **or**
- n < 100 (insufficient power — report as INCONCLUSIVE, not as a pass)

## Multiple comparisons — handled explicitly

Searching N wallets and reporting the best is guaranteed to find a winner by chance. This
design's control is the **holdout window**, not a correction formula: the K wallets are chosen
without ever seeing holdout data, so the holdout result is a genuine out-of-sample test.

Additional guard: the **full holdout distribution across all wallets** is reported alongside
the K, so a reader can see whether the K are genuinely separated or merely the tail of noise.
If the K's holdout median is not above the 75th percentile of all wallets' holdout medians,
the result is reported as **not distinguishable from selection noise**, regardless of p-value.

## Rules of conduct

1. No parameter in this document changes after collection starts.
2. The holdout is not examined until collection is stopped and the split boundary is fixed.
3. No re-running with a different K, horizon, or n-threshold to find a pass. Any such
   exploration is a new hypothesis and requires a new pre-registration.
4. v1 and v3 data are never pooled.
5. If the result is negative, it is reported as negative, in writing, with the same rigour as
   a positive one.

## Honest prior

**~25–30%** that H1 passes. Reasoning: selection is demonstrably the live variable, but even a
correctly chosen wallet is followed *after* its own market impact and after MEV, so a real edge
may not be transferable. Trap 2 (scoring wallets on past returns selects for luck) is the
primary reason for the low prior, and the holdout exists specifically to catch it.

## What a pass would and would not mean

**Would mean:** wallet selection carries information, and a hold-and-exit strategy is worth
developing properly.

**Would not mean:** that the strategy is profitable at $52, or that it survives real execution
slippage at size. Those are separate tests (v4 territory).

---

# AMENDMENT v3.1 — universe scale and the latency allowance

**Made before any v3 collection began. No v3 data has been examined. The v3 rules above are
otherwise unchanged.**

## What changed and why

v3 originally assumed a universe of "hundreds" trackable by websocket. Building it revealed
two facts:

1. The universe is **4,533 wallets** (`wallets_v3.json`), extracted from
   `discovered_wallets.json` (545 discovery events), `tracked_wallets.json`, and observed-buy
   records. Selection is by observed activity only, as specified — never by returns.
2. **Websocket capacity is ~20–25 wallets**, not 4,533. The free public endpoint broke at 64
   subscriptions and was stable at 20. So the universe cannot be tracked by websocket alone.

This is a measurement constraint, not a change of hypothesis. It is recorded here rather than
discovered later.

## Tiered tracking

- **Tier A — websocket, ~20–25 wallets.** Highest observed buy counts. Same-slot latency.
  Seeds the universe but is *itself a frequency-ranked selection*, which is the bias v1
  identified; Tier A alone cannot answer H1.
- **Tier B — poll rotation, unbiased random sample.** Tracking all 4,533 by poll is
  arithmetically impossible inside the latency allowance: at a 60 s poll and batch B, worst-case
  rotation latency is `(N/B)×60 s`, so a 900 s ceiling permits at most `15×B` wallets. With B=20
  that is **300 wallets** (RPC 28,800/day, under the 40,000 cap). Tier B is therefore a
  **deterministic random sample of 300** from the 4,533 (`wallets_v3_poll.json`, seed 20261010,
  recorded).

  Random sampling is the point: **unlike Tier A, Tier B is not ranked by activity**, so it is not
  subject to the frequency-selection bias. A full rotation takes 15 cycles ≈ 15 minutes, so every
  Tier B signal has latency ≤ 900 s by construction.

  Limitation, stated plainly: 300 of 4,533 is 6.6% of the universe. If the informative wallets are
  concentrated in the unsampled 93%, v3 will miss them. This is a power limitation, not a bias,
  and it is recorded before collection.

Signals from both tiers are recorded; tier is stored on each signal.

## Latency allowance (the substantive amendment)

The v1 rule "primary pool = latency ≤ 60 s" is **relaxed to ≤ 900 s for v3**.

Justification: v1 measured *detection speed* because speed was the hypothesis. v3 measures
*wallet quality* — whether ranking wallets on one period predicts returns in another. A lagged
entry is not a flaw here; it is the realistic condition, since a larger universe forces slower
detection. If anything it makes v3 *harder*, because entering later captures less of any pop.

This relaxation is recorded before collection. It is not available for v1 or v4.

## Power requirement, restated

The holdout needs **n ≥ 100** usable signals from the K selected wallets. With a 4,533-wallet
universe and unbiased rotation, that requires **several days** of collection, not hours.
Collection stops when either n ≥ 100 in the holdout is reached, or 7 days elapse. That
stopping rule is fixed now and may not be extended to chase a result.

## Honest prior, revised

**~10–15%** (down from 25–30%). Reason: `kt_portfolio.py` showed the mean net return is itself
negative (−6.5% at 4 h, CI [−17.7%, +6.6%]) and that excluding the 10 biggest winners the mean
is **−7.5%** at 900 s and −22% at 4 h. For selection to rescue this, the K wallets would need to
raise the *mean* enough to clear a −7.5% baseline. That is a very large effect to ask of wallet
selection alone.

**This prior is recorded so that a negative result cannot later be reframed as a surprise, and a
positive one cannot be dismissed as impossible.**

---

# AMENDMENT v3.2 — instrument defects found before any holdout data was examined

**Made 2026-10-10, after 1.1 h of v3.1 collection (89 signals, all Tier A/B, none examined for
outcome). No holdout window has been inspected, no return statistic has been computed, and the
split boundary has not been fixed. The hypothesis, pass criterion, kill criterion, K, horizon,
training fraction and stopping rule above are UNCHANGED. This amendment repairs the measuring
instrument, not the question.**

## Why this exists

After v3.1 started collecting, the data path between "a wallet bought" and "the verdict is
computed" was audited against this document. Four defects were found. Three of them would have
produced a **wrong result that looked clean**, and one would have **silently pooled** the fixed
data with the data it invalidated. They are recorded here rather than fixed quietly, because a
silently repaired instrument is indistinguishable from a tuned one.

## Defect 1 (fatal): the v3 verdict applied the v1 latency rule

`kt_wallets.py` filtered candidate signals with a hard-coded literal:

```python
lat = s.get("latency_sec_slot")
if lat is None or lat > 60.0:      # <-- the v1 rule, 15x tighter than v3's
    continue
```

Amendment v3.1 states: *"The v1 rule 'primary pool = latency ≤ 60 s' is relaxed to ≤ 900 s for
v3."* The script was never updated, and because the value was a literal it did not read
`config.json` — so no configuration change could have corrected it.

Measured effect on the 67 v3.1 signals that were usable and had a 300 s fill:

| Tier | Candidate rows | Kept by the 60 s filter | Excluded | median slot-latency |
|---|---|---|---|---|
| A — websocket, frequency-ranked | 50 | 50 | **0%** | 0 s |
| B — poll, random sample | 17 | 7 | **59%** | 80 s |

The filter deleted the majority of the *unbiased* tier and nothing at all from the
*frequency-ranked* tier. Run unamended, v3.1 would have reported a holdout verdict computed
essentially on Tier A — the exact selection bias v1 identified and the reason Tier B was built.
A negative result would have been uninterpretable and would have looked decisive.

## Defect 2: the ingest gate contradicted the registered allowance

`config.json` carried `detection.max_signal_age_sec: 180` while this document and
`wallets_v3_poll.json` (`_max_latency_sec: 900`) both register **900 s**. Every candidate older
than 180 s was discarded at ingest.

Measured, in the v3.1 window: 393 Tier B candidates were discarded and 28 recorded. All 393
discards were Tier B; **Tier A had zero** (websocket detection is same-slot). Tier B's maximum
observed wall latency was 176 s — pressed against the gate, which confirms the gate, not the
900 s allowance, was the binding constraint.

Measured age distribution of the 393 discards, which is what makes the size of this defect
honest rather than dramatic:

| Gate | Recovered | Share |
|---|---|---|
| 180 s (as configured) | 0 | 0% |
| 900 s (as registered) | 52 | 13% |
| 2700 s | 126 | 32% |
| > 3600 s | 254 | 65% |

Median discarded age **18,461 s (5.1 h)**. The 65% older than an hour are **first-poll backfill
of dormant wallets**, not recently-tradeable signals. Correcting the gate to the registered 900 s
therefore raises Tier B yield by roughly **2.9×**, not by the ~14× that "393 discarded vs 28
kept" would suggest. That distinction is recorded because the larger figure was the first one
computed here, and it was wrong.

## Defect 3 (the dangerous one): the gate was invisible to the config fingerprint

`kt_lib.py` listed `max_signal_age_sec` in `_FP_IGNORE_EXACT`, commented *"data-cleaning hygiene
only: changes WHICH stale signals are discarded, not the measurement."*

That was **true for v1**, where the ingest gate (180 s) was wider than the primary pool (60 s) and
therefore could not bind. It is **false for v3**, where the registered allowance is 900 s, so the
180 s gate *defined* the primary pool and was a substantive test parameter.

Because the key was ignored, changing it left the fingerprint untouched:

```
before any change        6a9f1ff9c87aeea0
after gate 180 -> 900    6a9f1ff9c87aeea0   <- UNCHANGED
after prereg_version 1->2 1b6d50f8e7c81c05  <- changed
```

Had Defect 2 been fixed without also changing a fingerprinted key, **v3.1 and v3.2 data would
have carried the same fingerprint and been silently pooled in every analysis** — violating
"do not pool across config fingerprints", with no error and no warning. The fingerprint is what
enforces separation; a substantive parameter outside it makes that protection fail open.

## Defect 4: the "≤ 900 s by construction" guarantee was arithmetically wrong

v3.1 justified Tier B with `rotation = (N/B) × 60 s = (300/20) × 60 = 900 s`. That omits the
**per-batch RPC duration**. `poll_loop` is `poll_once()` (a real, blocking RPC batch) followed by
`sleep(poll_interval_sec)`; the batch itself is not free.

Measured: **169 s per 20-wallet batch**, i.e. ≈49 s of RPC work plus the interval. A full
300-wallet rotation is therefore **15 × 169 = 2535 s (42 min)**, not 900 s. Independent
cross-check on the mechanism: predicted Tier B capture `180/2535 = 7.10%` against observed
`28/374 = 7.5%`.

Two further arithmetic errors in the same paragraph:

- The RPC estimate of **28,800/day** assumed **1 call per wallet per rotation**. Actual is ~3.07
  (`getSignaturesForAddress` plus `getTransaction` per new signature). The measured steady-state
  burn is ~31,400/day.
- A **genuine** 900 s rotation over 300 wallets would cost roughly **88,000 RPC calls/day**
  against the configured 40,000 cap. **The registered latency guarantee and the registered RPC
  budget cannot both hold.** The v3.1 design was infeasible as written; the rig resolved the
  conflict silently by rotating more slowly, and the 180 s gate then converted that into a 13%
  effective capture of eligible signals. `poll_interval_sec` was also 120 in config against the
  60 recorded in `wallets_v3_poll.json`.

## Defect 5: slot-based latency was inflated by an unmeasured slot-duration constant

`kt_run.py` computed slot-based latency as `(detect_slot - tx_slot) * 0.4`, commented
"~400ms per slot". The 0.4 was asserted, never measured.

Checked against the data's own timestamps, for every pair of signals carrying both a `slot` and a
`block_time`:

| Δslot | Δblock_time | implied duration |
|---|---|---|
| −1024 | −223 s | 0.218 s/slot |
| −516 | −112 s | 0.217 s/slot |
| −730 | −161 s | 0.221 s/slot |
| 2502 | 546 s | 0.218 s/slot |

**0.218 s/slot, consistent across four independent pairs.** Recomputing the slot latencies at that
rate reproduced the wall-clock latencies to within 1–3 s (24.8 → 27.5, 250.0 → 252.7, 363.0 →
366.0, 524.8 → 526.0). So `latency_sec_slot` was inflated by **1.84×**, and the wall-clock figure
was the correct one.

Two consequences:

1. Every latency gate expressed in slot units was ~1.84× tighter than it read. The 60 s cap in
   `kt_wallets.py` was really a ≈33 s wall-clock cap; the 900 s cap would have been a ≈490 s cap,
   still excluding Tier B signals that the ingest gate had already admitted — i.e. Defects 1 and 5
   compounded.
2. The same constant sits in `_calibrate_clock`, which advances a reference block's `blockTime` by
   `(slot - ref) * slot_sec` with `ref = slot - 20`. Against a true 0.218, the 0.4 made that
   correction **≈+3.6 s too large** (20 × 0.182), understating every wall latency by the same
   amount.

`slot_sec` is now **measured** at each calibration from two dated reference slots (`getBlockTime`
at `slot-20` and `slot-60`), so it self-corrects across epochs rather than being asserted. The
v3.2 verdict gates on **wall** latency — the same measure the ingest gate applies — so the
collector and the verdict can no longer disagree about which signals are admissible.

*Residual, recorded:* the handful of v3.2 signals collected before this correction carry a wall
figure understated by ≈3.6 s. All are far below the 900 s cap (max observed 524.8 s), so the
effect on admission is nil; it is noted rather than repaired by another fingerprint bump, which
would orphan data for a 0.4%-of-allowance boundary effect.

**Note on the settled v1 result — recorded, not acted on.** `kt_verdict.py` applies its 60 s
primary-pool cap through the same slot-based measure, so v1's primary pool was effectively ≈33 s
of true latency rather than 60 s. That makes v1's negative verdict **more** conservative, not
less: it tested an even faster and more favourable subset and still measured −2.56% median net
with 39.7% positive (n=355). **v1 is not re-run, re-scored, or amended.** Re-opening a settled
result in the hope of improving it is precisely the failure mode this document exists to prevent.

## What changed in v3.2

| # | Change | Reason |
|---|---|---|
| 1 | `kt_wallets.py` reads `detection.max_signal_latency_sec_for_v3` (**900 s**) instead of the literal `60.0` | Defect 1. A new key, so `max_signal_latency_sec_for_primary` (60 s) is untouched and the settled **v1 verdict cannot be re-litigated** |
| 2 | `detection.max_signal_age_sec`: 180 → **900** | Defect 2. Aligns the ingest gate with this document and `wallets_v3_poll.json` |
| 3 | `max_signal_age_sec` removed from `_FP_IGNORE_EXACT` | Defect 3. It is a substantive parameter now and must stay fingerprinted |
| 4 | `preregistration_version`: 1 → **2** | Forces a new fingerprint so v3.1 and v3.2 can never be pooled |
| 5 | `poll_once` checks `blockTime` from `getSignaturesForAddress` **before** spending `getTransaction` | `getSignaturesForAddress` already returns `blockTime` (verified live), so out-of-allowance signatures now cost no RPC. Previously every discarded signal still cost a full `getTransaction` plus the `getSlot` that `ingest` issues |
| 6 | `poll_sig_limit`: 4 → **25** (same single RPC call) | `limit=4` permanently truncated any wallet trading more than 4× per rotation to its 4 most recent transactions, discarding history that was never even considered |
| 7 | `poll_interval_sec`: 120 → **130**; `poll_interval_sec` and `poll_rotation_batch` removed from `_FP_IGNORE_EXACT` | See "The RPC budget" below. 60 s matched this document's own assumption but overran the 40,000/day cap once the gate was corrected; 130 s is what the *measured* burn supports. Both keys are now fingerprinted, because the registration derives Tier B's rotation — and its sampling density — from exactly these two numbers |
| 8 | K is selected **from Tier B only**; the A+B union is reported as a secondary | Tier A is frequency-ranked. Selecting K from the union would let Tier A (≈3× the per-wallet usable-signal rate of Tier B) fill all five slots, and the holdout would then test the set this amendment exists to avoid. The union is printed for completeness and **is not the verdict** |
| 9 | `slot_sec` is measured per clock calibration from two dated reference slots, replacing the `0.4` literal | Defect 5. Removes a 1.84× inflation of `latency_sec_slot` and a ≈+3.6 s bias in `clock_offset_sec` |
| 10 | `kt_wallets.py` gates on **wall** latency (slot only as fallback) | Defect 5, and consistency: the verdict now uses the same measure the ingest gate applies, so a signal the collector admitted cannot be silently deleted at analysis |
| 11 | `poll_once` fetches **one `getSlot` per batch**, not one per signal | 64 of 342 RPC calls in the first v3.2 window went to a per-signal `getSlot`, purely to populate the slot-latency diagnostic, each one a blocking round-trip that lengthened every batch. Records now carry `detect_slot_source` so a batch-granular lower bound cannot be mistaken for a per-signal reading |
| 12 | `preregistration_version`: 2 → **3** | The instrument was finalised in two steps inside this one amendment (gate + fingerprint first, then the RPC-budget pacing). The intermediate window is discarded so that v3.2 is a single, homogeneous sampling regime rather than two pooled under one fingerprint — the precise error Defect 3 describes |
| 13 | `_load_existing` rehydrates pending forwards **only for the current fingerprint** | The tracker is budget-limited (`max_fetches` per pass) and works oldest-first, so re-queueing the 3,612 incomplete signals from the excluded v3.1 and legacy fingerprints starved the signals the v3.2 verdict reads, and spent the Jupiter budget — and the resulting 429 storm — on data already declared unanalysable. `seen_sigs` still absorbs every signature, so old signatures are not re-ingested. Measured effect: pending 3,777 → **57**, and usable 300 s rows 2 → 26 within minutes |
| 14 | `poll_interval_sec`: 130 → **220**; `preregistration_version`: 3 → **4** | Pacing was still ~49,000/day, 22% over the cap. Rather than run over-budget (which stalls ingest for hours each UTC day and makes sampling density vary systematically *within* every day), the interval is set so the measured burn fits with ~15% margin. This is the last instrument change; the two earlier v3.2 windows are discarded so the definitive collection is one stationary sampling regime |

Definitive fingerprint: **`63b8561732a5c6bc`**. All earlier data is excluded by fingerprint and
**is not pooled, not merged, and not reported as part of v3.2**:

| Fingerprint | What it is | Status |
|---|---|---|
| `d3753551dc…` | v1 / legacy | settled, separate test |
| `6a9f1ff9c87aeea0` | v3.1 (180 s gate, 60 s-config poll) | **discarded** — instrument defect |
| `2a7f0cfbbce45424` | v3.2 draft (gate fixed, per-signal `getSlot`) | **discarded** — instrument not final |
| `224d6bdb82639f44` | v3.2 draft (slot measured, 130 s pacing) | **discarded** — over RPC budget |
| **`63b8561732a5c6bc`** | **v3.2 definitive** | **the collection that counts** |

The v3.2 collection clock and the stopping rule run from the definitive fingerprint, not from the
earlier drafts.

## The RPC budget: what the corrected gate actually costs

Correcting Defect 2 does not merely *record* more signals — it **pays** for them. Every candidate
surviving the recency gate costs a `getTransaction`, and `ingest` additionally performs blocking
price lookups. Measured on the live rig, by the rig's own counter:

| Configuration | RPC calls/batch | batch period | implied burn |
|---|---|---|---|
| v3.1 (180 s gate, 120 s poll) | ~63 | ~224 s | ~24,000/day |
| v3.2 draft (900 s gate, 60 s poll) | 126 | 224 s | ~48,700/day |
| v3.2 + one `getSlot` per batch (60 s poll) | 67 | 99 s | ~57,400/day |
| **v3.2 final (130 s poll)** | ~67 | ~171 s expected | **~33,900/day expected** |

Two findings belong in the record:

1. **Removing the per-signal `getSlot` raised the burn rather than lowering it.** It cut 18.7% of
   the calls but cut the batch's wall time by more, so the loop simply cycled faster. The poll
   loop is **not budget-aware** — it spends RPC as fast as it can — so the only effective lever on
   the daily total is the sleep between batches. That is why `poll_interval_sec` is 130 and not
   the registered 60: 60 s is arithmetically incompatible with a 40,000/day cap once Tier B
   actually records the signals its 900 s allowance entitles it to.
2. **The RPC budget, not the latency allowance, is the binding constraint on this experiment.**
   With the gate corrected the rig can afford to rotate the 300-wallet sample only about every
   ~2,900 s, so roughly a third of each wallet's in-allowance trades are still observed. The
   remainder are lost **silently** — never fetched, never counted, with no field recording the
   omission. Yield is capped by budget, and the honest consequence is a longer collection and a
   smaller holdout n than the v3.1 power section assumed.

`max_rpc_calls_per_day` stays at 40,000 and the rig still hard-stops at the cap (`Rpc.call`
returns `None`, ingest halts until the 00:00 UTC reset). That is a fail-safe, but it costs
collection time, so burn is to be read off every poll line (`rpc_today=`) rather than assumed.

## What this does NOT change

H1. The pass criterion (holdout n ≥ 100, median > 0, one-sided sign test p < 0.05, above the 75th
percentile of all wallets). The kill criterion. K = 5. The 300 s primary horizon. The 60/40
train/holdout split by time. The n ≥ 25 training threshold. The stopping rule (**n ≥ 100 in the
holdout, or 7 days** — fixed, not extendable). The honest prior of **10–15%**.

The latency allowance was not *loosened* to make the test pass: later entry captures less of any
pop, so correcting the gate makes H1 **harder** to pass, not easier. It cannot manufacture a
false positive.

## Limitations this amendment does NOT fix

1. **Coverage.** Tier B remains a 300-of-4,533 (6.6%) deterministic random sample. If the
   informative wallets are concentrated in the unsampled 93.4%, v3.2 will miss them. A null
   result bounds *this sample*, not the universe.
2. **Rotation still exceeds 900 s.** After change 7 the rotation is expected to be ~1,600–2,000 s:
   the per-batch RPC duration cannot be made free, and a true 900 s rotation would exceed the RPC
   cap (Defect 4). The registered guarantee is therefore enforced **by the ingest gate** — a
   recorded Tier B signal is at most 900 s old by construction of the gate — rather than derived
   from the rotation. The shortfall costs **yield**, not latency correctness.
3. **Tier B resolves to a small active subset, not 300 wallets.** Measured after ~1 h of v3.2: only
   ~15 of 300 Tier B wallets had traded and ~7 had produced usable signals. The active ones are
   productive (top wallets ≈30 signals/h each), so the n ≥ 25 training threshold is reachable
   inside an hour *for them* — the power risk is **not** unreachable n. It is that **K = 5 will be
   selected from a pool of roughly 10–20 qualifying wallets**, because the discovered 4,533-wallet
   universe is mostly dormant. That weakens the *selection* step; the holdout test remains valid.
4. **RPC cap.** The 40,000/day budget resets at 00:00 UTC. If a full day of collection exhausts
   it, `Rpc.call` returns `None` and ingest stops for the remainder of that day. Burn is to be
   measured after restart, not assumed; `rpc_today` is logged on every poll.

**A result that is inconclusive under limitation 3 will be reported as INCONCLUSIVE, not as a
kill and not as a pass.**

---

# AMENDMENT v3.3 — pre-registered post-collection diagnostic: the clairvoyance bound on the holdout

**Made 2026-10-11, during v3.2 collection. No holdout data has been examined. This amendment does
NOT change H1, the pass criterion, the kill criterion, K, the 300 s horizon, the train/holdout
split, or the stopping rule. It adds a diagnostic and freezes its interpretation *before* the
number exists, so that it cannot be spun after the fact in either direction.**

## Why this exists

The v3.2 verification will report whether the K selected Tier B wallets show a positive holdout
median. That answers *"is there a signal?"* It does not answer *"is any signal capturable?"* — and
those are different questions. A wallet subset can carry a positive median net return at 300 s and
still be untradeable if the return lives in peaks no rule can reach.

`kt_verdict.py` already carries the tool: `max_excursion_pct()`, the **clairvoyance bound** — buy at
the signal, sell at the best price ever sampled afterwards, pay friction. Because that requires
per-signal future knowledge, it is an **upper bound on the performance of any exit rule applied to
the same entries**, and a **lower bound on the true peak**, since excursion is sampled only at
discrete horizons.

On the v1 signal set that bound was **positive** (+10.17%), which is exactly why the rig's own kill
logic (`kt_verdict.py:269`) refuses to kill on a non-positive median net alone while the bound is
positive — *"the universe does not pay, at any speed"* is only licensed when the bound is
non-positive. The v3 verdict needs the same branch, pre-specified rather than discovered.

## Frozen procedure — executed only AFTER the stopping rule fires

1. Run `kt_wallets.py` exactly as already pre-registered: 60/40 split by time, K = 5 from **Tier B
   only** by training median net 300 s, evaluated on the holdout. **The verdict is whatever that
   produces. Nothing below can change it.**
2. On the **holdout signals of those same K wallets**, compute `exc_net = max_excursion_pct −
   friction_pct` per signal.
3. Report: median, bootstrap 95% CI of the median, %positive, and the **capture ratio**
   `friction / median(exc_net)`.
4. Report mean and median of `max_excursion_pct` separately (the shape), as `kt_portfolio.py` does.

*Implementation note: `kt_wallets.py` does not compute this yet. Adding it is a read-only
computation over rows it already loads, and it must not be run before the stopping rule fires.*

## Frozen interpretation

| Observation | Reading |
|---|---|
| `median(exc_net) ≤ 0` | No exit rule can pay on the selected wallets' signals. The exit branch closes **with a number**, not a vibe. This kills the exit branch, **not** H1. |
| `median(exc_net) > 0`, capture ratio **> 0.5** | The prize is thin: a rule would have to capture more than half of an unobservable maximum to break even. **Do not build exit machinery.** Report and stop. |
| `median(exc_net) > 0`, capture ratio **≤ 0.5** | Potentially capturable. Exit design becomes a *separate*, newly pre-registered test. It is not attempted here. |
| `mean(max_excursion) ≫ median(max_excursion)` | Lottery shape. Record it: it implies any fixed take-profit destroys the mean, and any uncapped hold carries the decaying majority. |

## Explicitly forbidden uses

- This diagnostic **cannot pass H1** and **cannot rescue a failed H1**. A positive bound alongside a
  negative holdout median means the signals contain upside nobody can reach — that is not evidence
  of a strategy, it is evidence of a ceiling.
- It **cannot** be used to re-select K, change the horizon, change the n threshold, or extend
  collection. Any such use is a new hypothesis and requires a new pre-registration.
- It is **not** an interim look: it is not computed until the stopping rule has fired and the split
  boundary is fixed.

## Reference points recorded now, so the result is read in context

These are **v1 numbers on a different fingerprint** — context only, **never pooled** with v3.2.
They are recorded so a v3.2 bound of similar magnitude is not mistaken for a discovery.

- v1 clairvoyance bound: **+10.17%** median, CI [+7.27%, +13.53%], against ~2.2% round-trip friction
  → capture ratio **≈ 0.216 ("thin")**. Every measured exit rule on that set was negative.
- v1 shape: median peak **+10.32%** vs mean peak **+56.61%**.
- v1 baseline: median net 300 s **−2.56%**, 39.7% positive, n = 355.

