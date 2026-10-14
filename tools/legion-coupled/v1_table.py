"""Exact table rows for the v1 pool at current data, for correcting the writeup.

Pool = pre-registered v1 rule: usable, latency_sec_slot (fallback wall) <= 60, after
first-per-(wallet,mint) dedup, filtered to the v1 fingerprint.
"""
import os
import statistics as st
import sys

sys.path.insert(0, r"C:\killtest-rig")
os.chdir(r"C:\killtest-rig")
import kt_verdict as kv          # noqa: E402

V1_FP = "d3753551dc57aa1b"
sigs_all, completes = kv.fold({"log_dir": "logs"})
sigs, dropped = kv.dedup_first_per_wallet_mint(sigs_all)
sigs = [s for s in sigs if s.get("config_fp") == V1_FP]
usable = [s for s in sigs if s.get("entry_price") and s.get("usable")]


def lat(s):
    v = s.get("latency_sec_slot")
    return v if v is not None else s.get("latency_sec")


pool = [s for s in usable if lat(s) is not None and lat(s) <= 60.0]
print(f"v1 pool n={len(pool)}   (dedup dropped {dropped} of {len(sigs_all)} raw records)\n")
print(f"{'horizon':>8} {'median net':>12} {'% net>0':>9} {'n':>6}")
print("-" * 40)
for h in (30, 60, 300, 900, 3600):
    vals = [float((s.get("forward") or {})[str(h)]["net_pct"])
            for s in pool
            if (s.get("forward") or {}).get(str(h))
            and isinstance((s["forward"][str(h)] or {}).get("net_pct"), (int, float))]
    k = sum(1 for x in vals if x > 0)
    print(f"{h:>7}s {st.median(vals):>11.2f}% {k/len(vals)*100:>8.1f}% {len(vals):>6}")

exc = [kv.max_excursion_pct(s, completes) - float(s.get("friction_pct") or 0.0) for s in pool]
exc = [e for e in exc if e is not None]
lo, hi = kv.bootstrap_ci(exc)
pos = sum(1 for x in exc if x > 0) / len(exc) * 100
print(f"\nclairvoyance: n={len(exc)}  median {st.median(exc):+.2f}%  "
      f"CI [{lo:+.2f}%, {hi:+.2f}%]  %positive {pos:.1f}%")
print(f"mean max-excursion {st.mean(exc):+.2f}%   median {st.median(exc):+.2f}%")
print(f"measured friction (median, %/round-trip): "
      f"{st.median([float(s.get('friction_pct') or 0) for s in pool]):.2f}%")
print(f"capture ratio = friction / ceiling = "
      f"{st.median([float(s.get('friction_pct') or 0) for s in pool]) / st.median(exc):.3f}")
