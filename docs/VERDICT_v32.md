# KILL TEST — v3.2 Pre-registered verdict

**Result: KILL.** The criterion was frozen before collection; this is the outcome, published regardless of sign.

- Preregistration version: 4
- Config fingerprint: `63b8561732a5c6bc`
- Window closed: 2026-10-17 23:12Z

---

## The one number that matters

**Clairvoyance bound: median net max-excursion = −1.04%** (95% bootstrap CI [−1.16%, −0.95%])

Buy every signal, sell at the *best price sampled afterwards* — perfect future knowledge — and you still lose ~1% after friction. There is no speed, no selection rule, and no timing that survives this. The universe does not pay.

---

## The pre-registered criteria

| criterion | required | measured | result |
|---|---|---|---|
| sample size | n ≥ 200 | **n = 1,059** | PASS |
| median net @ 300s | > 0 | **−28.52%** | FAIL |
| sign test p (one-sided) | < 0.05 | **1.0000** | FAIL |
| clairvoyance bound | > 0 | **−1.04%** | FAIL |

```
>>> KILL — n is sufficient, the median net return is non-positive, AND the
    clairvoyance bound is non-positive. The universe does not pay, at any speed.
    STOP. Write it down. Do not retune, do not add wallets, do not rebuild.
```

---

## Forward returns, net of measured friction (primary pool, n = 1,059)

| horizon | median net | % net > 0 | p (one-sided) |
|---|---:|---:|---:|
| 30 s | **−23.24%** | 26.5% | 1.0000 |
| 60 s | −23.88% | 27.0% | 1.0000 |
| 5 min | **−28.52%** | 26.7% | 1.0000 |
| 15 min | −33.84% | 25.0% | 1.0000 |
| 1 hr | −44.89% | 22.9% | 1.0000 |
| 4 hr | −51.49% | 21.8% | 1.0000 |
| 24 hr | −65.08% | 18.2% | 1.0000 |

Gross (before friction) at 5 min was already −25.59%: the tracked wallets are buying tokens
that then dump, and copying them is buying their exit liquidity. Friction makes it ~3 points
worse; it is not the cause.

---

## Method (frozen before collection)

- **Friction:** depth-based, measured against an **independent mid** for 2,192 / 2,192 usable
  signals (100%) — not Jupiter-for-both, which forces slippage toward zero by construction and
  would understate cost. This makes a KILL robust; a PASS would not have been.
- **Minimum notional:** $50. Signals below it are dropped and counted (46.7% dropout rate, almost
  entirely `below_min_notional(<$50)`).
- **Primary pool:** detection latency ≤ 60 s (n = 1,501 raw; n = 1,059 with complete forward data).
- **Detection latency** (slot-based, clock-independent): median **0.0 s**, p90 544.5 s, max 1454 s.
  Wall-clock median 25.7 s. "Be faster" is not available as an excuse — the rig already detects at
  same-slot latency.
- **Signal count:** 20,672 logged → 5,048 after first-per-(wallet, mint) dedup (15,624 correlated
  repeats dropped) → 4,148 in this version → 2,192 usable.

---

## Correction log (this run)

These are published because the instrument is only as honest as its corrections.

1. **Defect #5 — integer overflow in the sign test.** `sign_test_p()` computed
   `math.comb(n, i)` directly; at n ≈ 1500 the integer is too large to convert to float and the
   verdict crashed (`OverflowError: int too large to convert to float`). Fixed by computing the
   binomial tail in log-space — mathematically identical, numerically stable. The methodology did
   not change; the implementation did.
2. **31.6-hour collection outage.** An unplanned machine restart stopped the collector from
   2026-10-16 ~09:31Z to 2026-10-17 ~17:04Z. Data up to the stop is intact; the gap is documented,
   not hidden, and does not affect the verdict (n = 1,059 ≫ 200).
3. **One outlier wallet.** `B3duvci7hDoMsqA8FJf1dp2zVHRVZwvf9DdhbenE7E8N` showed median net +14.18%
   with n = 24 (95.8% positive, p = 0.0000) — the only positive wallet among 18. n = 24 is far too
   small to trust, and the pre-registration forbids retuning or chasing it. It is recorded as an
   observation, not a strategy.

---

## Per-wallet scoreboard (primary pool, ≥ 10 signals)

The outlier at the top is noise-sized; the rest are unambiguous.

| wallet | n | median net 5m | % > 0 |
|---|---:|---:|---:|
| B3duvci7…E8N | 24 | **+14.18%** | 95.8% |
| 5KRFck…YMU | 17 | +2.38% | 58.8% |
| wN3jfc…KR3 | 11 | +1.01% | 72.7% |
| 8nXfFf…bBn | 20 | −1.44% | 50.0% |
| 5KXDF6…6tD | 79 | −1.51% | 24.1% |
| 71pAfN…dAp | 72 | −3.74% | 30.6% |
| 8zkgFV…NsZ | 303 | −38.59% | 23.4% |
| 5owkcH…bq | 106 | −61.46% | 13.2% |
| 34rTaB…rPG | 77 | −62.80% | 19.5% |
| E4LDQz…tQR | 18 | −66.26% | 16.7% |

---

## What this settles

This is the fourth pre-registered evaluation and the most decisive. It is the answer to the
question the whole project was built to ask — *does copying tracked Solana wallets pay, net of
honestly measured friction?*

**No. Not at any speed, not with any selection, not even with perfect future knowledge of the exit.**

The instrument now has five documented defects, all found and published: the four discovered in
earlier evaluations, and the sign-test overflow found while producing this verdict. The negative
result stands because the friction model is the honest one and the clairvoyance bound is the
strongest possible test.

Nothing here is for sale and nothing here is a strategy. It is a measurement, published because a
negative result is still a result.
