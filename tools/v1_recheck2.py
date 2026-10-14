"""Variant check: could the writeup's numbers come from a DIFFERENT pool definition?

Before correcting anything, rule out that the writeup is right under some other defensible
definition. Variants tried: latency filter off (--all), slot-only, wall-only, and a sweep of
horizons. If the writeup's -1.5% / -8.1% / +3.2% appear under any variant, it was differently
defined rather than wrong, and must not be "corrected".
"""
import os
import statistics as st
import sys

sys.path.insert(0, r"C:\killtest-rig")
os.chdir(r"C:\killtest-rig")

import kt_verdict as kv          # noqa: E402

V1_FP = "d3753551dc57aa1b"
sigs_all, completes = kv.fold({"log_dir": "logs"})
sigs, _ = kv.dedup_first_per_wallet_mint(sigs_all)
sigs = [s for s in sigs if s.get("config_fp") == V1_FP]
usable = [s for s in sigs if s.get("entry_price") and s.get("usable")]

VARIANTS = {
    "no filter (--all)": lambda s: True,
    "slot <= 60": lambda s: isinstance(s.get("latency_sec_slot"), (int, float))
                            and s["latency_sec_slot"] <= 60,
    "wall <= 60": lambda s: isinstance(s.get("latency_sec"), (int, float))
                            and s["latency_sec"] <= 60,
    "slot-preferred <= 60 (v1 rule)": lambda s: (s["latency_sec_slot"]
                                                 if s.get("latency_sec_slot") is not None
                                                 else s.get("latency_sec")) is not None
                            and (s["latency_sec_slot"] if s.get("latency_sec_slot") is not None
                                 else s["latency_sec"]) <= 60,
}

HORIZONS = (30, 60, 300, 900, 3600, 14400, 86400)

print("median NET return (%) by horizon, per pool definition")
print("target from the writeup: -1.5% at 5 min, -8.1% at 1 h; clairvoyance +3.2%\n")
hdr = "pool".ljust(32) + "".join(f"{h:>9}" for h in HORIZONS)
print(hdr)
print("-" * len(hdr))
for name, pred in VARIANTS.items():
    pool = [s for s in usable if pred(s)]
    cells = []
    for h in HORIZONS:
        vals = [float((s.get("forward") or {})[str(h)]["net_pct"])
                for s in pool
                if (s.get("forward") or {}).get(str(h))
                and isinstance((s["forward"][str(h)] or {}).get("net_pct"), (int, float))]
        cells.append(f"{st.median(vals):>9.2f}" if vals else f"{'-':>9}")
    print(f"{name} (n={len(pool)})".ljust(32) + "".join(cells))

print("\nclairvoyance bound (median net max-excursion) per pool definition")
print("target from the writeup: +3.2%\n")
for name, pred in VARIANTS.items():
    pool = [s for s in usable if pred(s)]
    exc = []
    for s in pool:
        e = kv.max_excursion_pct(s, completes)
        if e is not None:
            exc.append(e - float(s.get("friction_pct") or 0.0))
    if exc:
        lo, hi = kv.bootstrap_ci(exc)
        ci = f"[{lo:+.2f}, {hi:+.2f}]" if lo is not None else "n/a"
        print(f"  {name:<32} n={len(exc):<5} median {st.median(exc):+7.2f}%   95% CI {ci}")
    else:
        print(f"  {name:<32} (no data)")

print("\nmean vs median of max-excursion (the v1 payoff shape, v1 pool):")
pool = [s for s in usable if VARIANTS["slot-preferred <= 60 (v1 rule)"](s)]
pairs = [(kv.max_excursion_pct(s, completes), float(s.get("friction_pct") or 0.0))
         for s in pool]
pairs = [(e, f) for e, f in pairs if e is not None]
if pairs:
    raw = [e for e, _ in pairs]
    net = [e - f for e, f in pairs]
    print(f"  n={len(pairs)}")
    print(f"  GROSS max-excursion : median {st.median(raw):+7.2f}%   MEAN {st.mean(raw):+7.2f}%"
          f"   max {max(raw):+.1f}%")
    print(f"  NET   max-excursion : median {st.median(net):+7.2f}%   MEAN {st.mean(net):+7.2f}%")
    trimmed = sorted(net)[:-10]
    if trimmed:
        print(f"  excluding the top 10 NET outcomes, mean = {st.mean(trimmed):+.2f}%  "
              f"(n={len(trimmed)})")
