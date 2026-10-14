# I built a pre-registered test for Solana wallet copy-trading. It failed.

*A negative result with a falsifiable design — which is rarer in crypto than another bot.*

---

## Summary

Over seven months I built and ran an automated Solana micro-cap copy-trading system. It lost money.
Rather than iterate on parameters for an eighth month, I built a separate rig to test the **premise**
— *is there any edge in "these wallets bought X"?* — with a pre-registered pass/kill criterion.

The premise failed, and the interesting part is *how* it failed. Three measurements, each
independent:

| Test | Result | Verdict |
|---|---|---|
| Forward returns (buy and hold) | median net **−2.51%** at 5 min, **−11.33%** at 1 h | negative at every horizon |
| Short-horizon perfect-exit ceiling | median **−0.78%** in the first 30 s, ≈**0%** by 300 s | no fast pop to capture |
| Clairvoyance bound, all horizons (perfect exit) | median **+10.17%**, 95% CI **[+7.27%, +13.89%]** | a ceiling exists — hours out, not seconds |
| Realistic take-profit/stop rules | **every** combination negative; best **−1.07%** | the ceiling is unreachable |

That last row is the finding. A pop exists, and any consistent rule designed to capture it
costs more than it collects — because the value sits in a fat right tail that a take-profit
truncates. The second row is the sharper version of the same point: the perfect exit *inside the
window a fast strategy would trade in* does not even cover friction, so the prize is not merely
hard to capture, it is hours away.

---

## Why the rig had to exist

Every earlier attempt to improve the system was scored by the system's own telemetry, and that
telemetry was not measuring edge. Concretely, from an audit of the codebase:

- A `signal_quality: "clean"` label was selection-conditioned rather than predictive, and did not
  reproduce out of sample (−$0.044/trade for "clean" vs −$0.193/trade for unlabelled).
- Wallet P&L was numerically broken (mean +501,842,528%, max 263 billion %).
- A skip-statistics module was blind to the volume gate it was supposed to measure.
- The momentum watchlist could never intersect the candidate universe (max achievable score 55.9
  against thresholds of 60/65) — it was structurally dead code.
- The backtest *was* genuinely point-in-time (no look-ahead found), but it was the only honest
  instrument in the system.

Tuning against that is fitting noise. So the instrument came first.

## Method

**Pre-registration.** Hypothesis, pass criterion, kill criterion, minimum n, and friction model
were frozen in writing before data collection, with a config fingerprint enforced so signals from
different criteria sets could not be pooled.

**Detection.** WebSocket `logsSubscribe` with per-wallet `mentions` filters, plus a polling
backstop. 20 wallets selected by trade frequency, covering 85% of observed buy volume.

**Latency measured clock-independently.** Wall-clock latency is corruptible by host clock drift,
so latency is primarily derived from **slot numbers** (`(detect_slot − tx_slot) × slot_sec`). This
mattered: the machine's clock free-ran ~11 s/hour with NTP misconfigured, and a calibration bug of
my own biased wall-clock latency by ~8 s. The slot-based figure was unaffected by either.
*(Correction: the slot duration was originally assumed at 0.4 s. It was later **measured** from
`block_time`/`slot` pairs at **0.218–0.225 s**, so every slot-based latency was inflated ~1.84×.
The "≤60 s" pool below was therefore effectively ≈33 s of true latency — which makes the negative
result stronger, not weaker, since the pool was faster than it claimed.)*

**Friction measured, not assumed.** A previously "measured" ~0% slippage was circular — it
compared a Jupiter mid against a Jupiter quote. It was replaced with **depth-based impact**
($1 vs $50 notional quotes) against an independent mid. *(Correction, 2026-10-12: this line used to
quote "~1.05–1.13% per side, versus a modelled 2.00%". **That figure is not reproducible from the
recorded data** — re-derived per-side impact over the v1 primary pool is median **0.40%**, mean
**1.42%**, p75 0.74%, p90 2.76%, and a 5%-trimmed mean of 0.69%; no summary statistic lands in
1.05–1.13%. So the reproducible statement is: median round-trip friction **1.46%**, with a heavy
tail (mean 3.48% round trip, p99 21.8% per side). The mean is not a usable summary — it is carried by
a handful of extreme measured impacts, and in the v3.2 pool such records reach 4,900% per side. Every
ceiling in this document therefore subtracts **each signal's own** recorded friction and additionally
stress-tests a flat 2.78% and 4.60% round trip, so no conclusion depends on the disputed summary.)*

**Correlated repeats deduplicated.** The same mint bought by several tracked wallets, or one wallet
buying repeatedly, was previously counted as independent evidence. First-per-(wallet, mint) dedup
removed **four fifths** of all records (v1 dataset: 3,991 raw → 757 unique).

**Falsification built in.** The decisive statistic is the **clairvoyance bound**: buy at the signal,
sell at the best sampled price afterwards, pay measured friction. It is latency-independent and
clock-independent, and it bounds what *any* strategy on this signal could achieve.

## The finding that took longest to see

Detection latency was stuck at a median of 122 s. The websocket reported `subscribed; listening`
with no errors, yet delivered **zero notifications** — a counter I added specifically for this
showed `ws_notifs=0`. Detection was silently falling back to the 60-second poll.

Cause: the rig preferred the websocket host matching the healthy RPC endpoint. That provider
(Alexander/Alchemy-class) accepts subscriptions and pushes nothing. A probe of six free endpoints
found the **official public Solana websocket delivers in ~1 second**. After the fix: median slot
latency **0.0 s** — same-slot detection.

The generalisable lesson: **the failure was quiet, not broken.** A connected, error-free,
non-delivering stream is worse than a crashing one.

## Results

**Forward returns, net of measured friction** (primary pool, latency ≤60 s, n=357):

| Horizon | median net | % net > 0 | n |
|---|---|---|---|
| 30 s | −2.44% | 31.1% | 357 |
| 60 s | −2.56% | 32.8% | 357 |
| 300 s | −2.51% | 40.1% | 357 |
| 900 s | −4.40% | 37.8% | 357 |
| 3600 s | −11.33% | 33.3% | 357 |

**Clairvoyance bound** (n=357): median **+10.17%**, 95% bootstrap CI **[+7.27%, +13.89%]**,
70.3% positive. Note the shape: mean max-excursion is **+48.89%** against a median of **+10.17%**.
The upside is real, but it lives in a fat right tail — **and it is hours away, not seconds.**

**The short-horizon ceiling — the last open question, answered (2026-10-11).** The rule sweep's
blind spot was the first 30 seconds. A dense sampler closed it: 51,965 price samples at a nominal
3-second tick over the first 120 s of a signal's life, for 1,307 signals (127 of them in the v1
primary pool; `logs/fastpath.jsonl`). Restricting the *clairvoyance* bound to short windows — sell
at the best price observed inside the window, pay measured friction once — gives:

| Window | perfect-exit ceiling, net of friction | gross, before friction | clears friction | n |
|---|---|---|---|---|
| 30 s (dense sampler, basis-adjusted) | **−0.78%** (CI [−0.95, −0.65]) | **+0.00%** | 27.7% | 603 |
| 60 s | **−0.73%** (CI [−0.90, −0.65]) | **+0.00%** | 29.2% | 603 |
| 120 s | **−0.68%** (CI [−0.85, −0.65]) | **+0.00%** | 32.0% | 603 |
| 30 s (`signals.jsonl`, all usable) | **−1.64%** (CI [−2.08, −1.35]) | — | 33.3% | 1,143 |
| 60 s | **−1.19%** (CI [−1.58, −0.97]) | — | 37.4% | 1,143 |
| 300 s | **−0.45%** (CI [−0.66, +0.14]) | — | 47.3% | 1,143 |
| 300 s (v1 primary) | **+0.17%** (CI [−0.74, +1.79]) | — | 50.4% | 357 |
| 900 s (v1 primary) | **+2.13%** (CI [+0.48, +5.13]) | — | 58.3% | 357 |
| 3600 s (v1 primary) | **+6.53%** (CI [+2.70, +9.98]) | — | 66.1% | 357 |

Three things follow.

First, **the median signal's best price in the first two minutes is the first price observed.**
The gross short-window ceiling is exactly **+0.00%** at every window out to 120 s: in 62–72% of
paths, no later sample ever exceeds the first observation by even 0.5 pp. The pop the rule sweep
was looking for is not hiding in the first 30 seconds — for the median signal there is no pop.

Second, **the short-window ceiling does not clear friction.** Median round-trip friction in this
data is **1.26–1.45%** (fastpath subsets 1.26–1.28%; v1 primary 1.45%). Against that, the median
perfect-exit ceiling is **−0.68% to −1.64%** across the first 30–120 s, and only **27–33%** of
signals clear friction *even at the peak*. It is negative under **every** friction convention: at the
measured median round trip (**1.46%**) the 30 s ceiling is −0.78%; at double that (2.92%) it is
−2.92%; at the originally modelled 4.60% it is −4.60%. The most generous assumption available is the
smallest friction, and even that leaves the median signal down after a perfect exit.

Third, **the +10.17% clairvoyance bound is not a fast-money result.** It is the maximum over every
price the tracker recorded, including the running maximum carried to the end of tracking, and it
grows monotonically with the window: ≈0% at 300 s (v1 +0.17%, all-usables −0.45%), +2.13% at
900 s, +6.53% at 1 h, +10.17% unrestricted. The prize is real and it sits **hours** out. That is
consistent with everything else here — the runners are long-horizon lottery tickets — and it
closes the last version of the premise that could have survived: there is no minutes-scale window
in which a *perfect exit* breaks even, so no achievable rule can.

*Measurement notes, because these are exactly the choices that flatter a result.* (1) The fastpath
ceiling is quoted **basis-adjusted** — measured from the first observed sample, not from the
recorded `entry_price` — because the sampler prices on Jupiter while the entry price is
DexScreener-first, and the first sample sits a median **−6.1%** from entry. Against the recorded
entry price the same ceiling reads −2.54% to −4.14%; the basis-adjusted figure is the internally
consistent one (one price source at both ends) and it is the one *generous* to the thesis.
(2) The sampler is nominally 3-second, but upstream price caching leaves a **median of 5 distinct
price points per 41-sample path**, so it is coarser than its name; it covers 12% of v1 signals and
19% of v3.2 signals. The subset is not cherry-picked in the thesis's favour — it is mildly
*better* than the signals it misses (net@30s median +0.25 to +0.45 pp), which makes the negative
answer more conservative, not less. (3) The move between detection and the first sample (0–3 s) is
excluded and cannot be recovered from this data, which can only make the true short ceiling
modestly higher, never materially. (4) 33 of 1,265 pooled signals carry out-of-range friction
(>20%, the largest ~9,800%); they are genuine measured impact on illiquid pools, they wreck only
the means, and dropping them moves every median in the table by **≤0.55 pp**, so they are not
carrying the conclusion. (5) **A forward labelled "+h s" is not always fetched at h seconds**, and
this applies to the horizon-sampled rows above *and* to the forward-return table earlier. Each
forward record carries its true elapsed age, and measured on this data the bar used for h=30 s is
fetched at a **median age of 87 s** (91% of them more than 20% late), h=60 s at **116 s** (85%),
h=300 s at **376 s** (55%), with p90 ages of 404 s, 431 s and 664 s. The cause is structural, not a
bug: a signal's tracking clock starts at detection, but its record — and therefore its first
tracking pass — is only written after the entry-price and depth-quote calls, which under
rate-limiting can take tens of seconds. So the short-horizon columns are *age* labels, not precise
sampling times, and the dense sampler in the first table is the only source here that actually
measures the first 30–120 seconds from detection. **And the defect flatters the thesis, so the
horizon-sampled rows above are upper bounds.** Restricting every fill to within 1.2× its own horizon
(v1 primary / all usable) gives **−3.25% / −2.08%** at 30 s, **−2.28% / −1.81%** at 60 s,
**−0.97% / −1.14%** at 300 s, **−0.05% / −0.60%** at 900 s and **+1.87% / +1.08%** at 1 h — *lower
at every window through 900 s*, and positive only at 1 h. The mechanism is unremarkable once stated:
a bar fetched late sits further into the token's decay, and a maximum taken over a longer effective
window can only rise. The age-clean subset is thinner (n=51/110/249/322/355 for v1) because signals
whose bars are all late drop out, so it is a different and smaller population — but it is the honest
one, and it strengthens the conclusion rather than weakening it: at 300 s the ceiling is not merely
≈0%, it is outright negative.

**Robustness — clustered inference.** The verdict statistic is a sign test, which assumes
independent observations, and these signals are not independent: they cluster by wallet (one
wallet's trades share its strategy and timing) and by mint (one mint's outcome is shared by every
signal on it). Recomputing with that accounted for:

| Clustering | clusters | SE inflation | 95% CI of the median | cluster-level sign test |
|---|---|---|---|---|
| naive (iid) | — | 1.00× | [−4.44%, −1.33%] | — |
| by wallet | 15 | **1.78×** | **[−5.36%, −0.39%]** | 3/15 positive, p=0.996 |
| by mint | 192 | 1.07× | **[−4.35%, −1.15%]** | 73/192 positive, p=0.9997 |

The conclusion survives — every clustered interval still excludes zero, and the wallet-level sign
test is overwhelmingly negative. The honest correction is that the naive interval was **too
narrow** by a factor of ~1.8 in variance, so the original significance was overstated even though
its direction was right.

**Robustness — power.** Against the 50% null, this design could detect a true positive-rate of
**56.6%** (n=357, one-sided α=0.05, power 80%). The observed rate is **40.1%** — well *below* the
null rather than hovering near it. The mean-based minimum detectable effect is **±8.90 pp**
(wallet-clustered), against a perfect-exit ceiling whose mean is **+48.9%**. In other words: the
study was powered to see an edge of the size the ceiling permits, and saw none. This was not an
underpowered null.

**Rule sweep** (take-profit × stop × timeout — 60 combinations on the coarse path, 96 on the fine
3-second path): all negative. Best by mean net was **−1.07%** (TP +12% / SL −10% / timeout 300 s,
n=456) on the coarse path, and **−0.98%** (TP +12% / SL −5% / timeout 60 s, n=127) on the fine path.
The mechanism is visible in the comparison:

```
buy and hold to 900s :  mean  −0.16%   median −4.69%   win 36.6%
TP +2%, no stop      :  mean −11.87%   median +2.00%   win 53.9%
```

Adding a take-profit **raises the median and the win rate while collapsing the mean.** Buy-and-hold's
mean sits ~4.5pp *above* its median, carried by rare uncapped winners — and that tail is exactly what
a take-profit removes.

**Per-wallet dispersion** (real, though not individually significant):

```
8zkgFGVZ…  n=47   median net 5m = +4.35%   %>0 = 61.7%   p=0.07
922M9fBT…  n=44                   −1.65%         45.5%   p=0.77
F6pq4Unx…  n=41                   −2.22%         46.3%   p=0.73
3K7XMbqv…  n=52                   −2.82%         34.6%   p=0.99
nQEqsdvA…  n=51                   −3.76%         29.4%   p=0.999
13VK7ZrR…  n=16                   −6.52%         31.2%   p=0.96
HGXr65Ki…  n=93                   −7.50%         35.5%   p=0.998
```

Six of seven wallets are net negative, and the single positive one sits at n=47 — *mid-pack* by
activity, not low. So part of the earlier reading does not survive the larger sample. What the table
does support is narrower and still useful: **the most active wallet is the worst** (n=93, −7.50%),
consistent with frequency-ranked discovery recruiting bots and market makers. It does **not** support
the stronger claim that skill hides in inactivity — the least active wallet here (n=16) is one of the
worst, not the best.

## Independent confirmation from the live book

Separately, the system's own **52** closed paper trades — the book has kept trading since this was
first written, which is why the count moved: net **−$5.54**, expectancy **−$0.1065/trade**,
t = **−3.62**, bootstrap 95% CI **[−$0.164, −$0.050]** per trade, win rate 18/52. The conclusion is
unchanged: still net negative, still significant.

**Withdrawn, 2026-10-11:** a no-information benchmark was previously quoted here — coin-flip
entries capturing **54.2%** of notional against the system's **34.8%**. That number is withdrawn.
Its metric is defined nowhere in the codebase, and the trade record does not store the
maximum-favourable excursion it would require, so it can be neither reproduced nor checked. A
figure nobody can re-derive does not belong in a document whose only asset is that its numbers are
checkable.

The question it was reaching for — does entry *timing* carry information? — was instead tested
directly, with a **matched-holding control** on the rig's own dense price paths: enter at the signal
versus 3–60 s later, same mint, **same holding period**, so that memecoin decay cannot confound the
comparison (returns between two samples cancel the DexScreener↔Jupiter source basis exactly).
**The answer is no.** The median paired difference is **exactly 0**, 54% of pairs are ties, and a
cluster bootstrap over mints leaves the median at 0 in every resample. Entry timing after detection
carries no measurable information — consistent with the rest of this document: the question is
*whether* to enter, not *when*.

*Caveat, recorded because it nearly fooled me:* this analysis is **anchor-sensitive**. Anchoring one
sample earlier shows a confident +2.6 pp with a confidence interval excluding zero — a pure
artefact. Any version of this test must state its anchor.

An event study across **2,951 tracked signals** found median forward returns of **−9.7%** (1 h),
**−36.5%** (6 h), **−62.5%** (24 h), and **−86.9%** (7 d) — the lifecycle of a memecoin, not noise.
*(Source: the system's own `signal_tracker`, a separate dataset from the rig. Recomputed
2026-10-11; it is still accumulating, so these figures drift.)* The **means** tell the other half of
the story: at 1 h the mean is **+699%** against a median of −9.7%. A handful of violent winners
drag the mean hundreds of points above the median — which is precisely why any rule that sells into
strength destroys the only part of the distribution that pays.

## What I'd claim, and what I wouldn't

**Claimed:** for this population of wallets and this asset class, with measured friction, the
copy-trade signal did not produce positive expectancy under a pre-registered test.

**Not claimed:** that no Solana strategy works, or that these results generalise to other wallet
populations, longer horizons, or lower-friction venues. The rule sweep had a known blind spot —
forward samples start at 30 s, so a pop that occurs and decays inside the first 30 seconds is
invisible. A nominal 3-second sampler was built to close that gap; **it did close it, and the
answer is negative** (see *the short-horizon ceiling*, above). The median perfect-exit ceiling in
the first 30–120 s is −0.7% to −1.6%, and the median signal's best price in that window is its
first observed price. The blind spot is closed, not filled.

## What I'd do differently

1. **Gate on the ceiling *in the window you intend to trade*, not the all-horizon one.** The
   clairvoyance bound over every recorded horizon came out **positive** (+10.17%), which on its own
   would not have killed the premise — it is dominated by the 1 h and longer samples and so says
   nothing about speed. The cheap and decisive gate is the same computation restricted to the
   window the strategy would actually live in (30–300 s): here that is **≈0% at the median, i.e.
   below friction**, which settles the fast version of the premise in an afternoon instead of after
   weeks of exit-rule sweeps. Compute the ceiling inside the intended holding window, compare it to
   measured round-trip friction, and only then decide whether there is anything to build.
2. **Pre-register before collecting.** I drew a confident "structurally unprofitable" conclusion
   from n=38 and had to retract it as the sample grew. The discipline exists precisely because that
   instinct is strong.
3. **Make silent failures loud.** The single largest measurement error was a websocket that
   reported success and delivered nothing. Watchdogs on *delivery*, not on connection state.
4. **Never measure slippage against your own quote.** Use an independent mid, and use size.

## Reproducing

Rig, pre-registration document, and verdict tooling are self-contained Python: websocket ingestion
with polling backstop, RPC failover across rate-limited endpoints, atomic append-only stores,
depth-based friction measurement, and a pre-registered verdict with bootstrap confidence intervals.
Runs paper-only; reads no credentials.

---

*Correction, 2026-10-11: the forward-return and clairvoyance figures were originally quoted at
n≈166 and had gone stale as collection continued. They are recomputed here from the full n=357
dataset. No conclusion changed direction — the bound is still positive, still unreachable, and
every rule still loses — but the magnitudes moved materially: the ceiling is roughly 3× higher than
first reported, and the losses are larger.*

*The **rule-sweep numbers were re-verified on the same pass**, re-run against the v1 fingerprint on
the now-final data. The best rule by mean net is −1.07% coarse / −0.98% fine, not the −2.30%
originally quoted; and the buy-and-hold 900 s baseline is mean −0.16% / median −4.69% / win 36.6%,
not mean +2.69% / median −2.25% / win 41.5%. The mechanism the comparison illustrates is unchanged
and in fact sharper: a take-profit lifts the median from −4.69% to +2.00% and the win rate from
36.6% to 53.9% while driving the mean from −0.16% to −11.87%. The slot-duration and dedup figures
under Method were also corrected.*

*The **per-wallet table and the event study were also re-verified on the same pass.** The table now
shows all seven wallets with n≥10 (previously five, at n=16–35; now n=16–93), and the interpretive
claim attached to it was narrowed: what survives is that the most active wallet is the worst, not
that the best wallets are the least active. The event study recomputes within ~1.5pp of the figures
shown above; it drifted only because its source (`signal_tracker`) is still accumulating.*

*The **live paper book was re-derived too**, and its figures moved because the book never stopped
trading: 46 → **52** closed trades, net −$5.50 → **−$5.54**, expectancy −$0.120 → **−$0.1065**/trade,
t −4.12 → **−3.62**, CI [−$0.179, −$0.066] → **[−$0.164, −$0.050]**. Still negative, still
significant. The six extra trades were collectively near break-even, which is why expectancy
improved slightly rather than degrading.*

*Added 2026-10-11 — **two robustness sections**, clustered inference and power, now sit under
Results. Clustering by wallet inflates the standard error 1.78× and still leaves every interval
excluding zero, so the direction holds but the original significance was overstated. Power was
adequate: the design could detect a 56.6% positive-rate against a 50% null and observed 40.1%.*

*The **coin-flip benchmark quoted in this document has been withdrawn** (54.2% vs 34.8% of
notional). Its metric is defined nowhere in the codebase and the trade record lacks the
maximum-favourable excursion it needs, so it could not be reproduced — and an unreproducible
figure does not belong here. It has been replaced by a properly defined matched-holding control,
which finds that entry timing carries no information.*

*Added 2026-10-11 (late) — **the short-horizon ceiling**, the question this document previously
listed as its one open item, is now computed and sits under Results: the median perfect-exit
ceiling in the first 30–120 s is **−0.7% to −1.6%** net of measured friction, the gross ceiling in
that window is exactly **+0.00%**, and the +10.17% all-horizon bound is a ≥900 s phenomenon. The
blind-spot caveat under "What I'd claim" and the first item under "What I'd do differently" were
both rewritten to match. Recomputed from `logs/fastpath.jsonl` and `logs/signals.jsonl` by
`short_ceiling.py`, which also reproduces the published v1 table and the +10.17% bound to the digit
from the rig's own `kt_verdict.fold()` before reporting anything new. Two documentation corrections
came out of the same pass: the Summary's rule-sweep figure still read −2.3% (the re-verified best
is **−1.07%**), and the third-row label "that third row is the finding" no longer matched the table
it pointed at.*

*Everything in this writeup has now been re-derived from the underlying data at least once. Where a
figure moved, the movement is recorded above rather than quietly overwritten.*

*Written to be falsifiable. If someone reruns this and gets a positive expectancy, the design
allows them to say so — which is more than most trading writeups permit.*
