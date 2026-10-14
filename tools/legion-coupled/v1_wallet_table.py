"""Re-verify the writeup's per-wallet dispersion table.

Mirrors kt_verdict.py's PER-WALLET SCOREBOARD: primary pool (usable, slot<=60, v1 fingerprint),
per wallet, signals carrying a 300 s forward net, wallets with n>=10, sorted by median desc.
Read-only.
"""
import collections
import os
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, r"C:\killtest-rig")
os.chdir(r"C:\killtest-rig")
import kt_verdict as kv          # noqa: E402

V1 = "d3753551dc57aa1b"
sigs_all, _ = kv.fold({"log_dir": "logs"})
sigs, _ = kv.dedup_first_per_wallet_mint(sigs_all)
sigs = [s for s in sigs if s.get("config_fp") == V1]
usable = [s for s in sigs if s.get("entry_price") and s.get("usable")]


def lat(s):
    v = s.get("latency_sec_slot")
    return v if v is not None else s.get("latency_sec")


pool = [s for s in usable if lat(s) is not None and lat(s) <= 60.0]

by_w = collections.defaultdict(list)
for s in pool:
    f = (s.get("forward") or {}).get("300")
    if f and isinstance(f.get("net_pct"), (int, float)):
        by_w[s["wallet"]].append(float(f["net_pct"]))

rows = [(w, v) for w, v in by_w.items() if len(v) >= 10]
print(f"v1 primary pool n={len(pool)}; wallets with n>=10 usable 5-min outcomes: {len(rows)}\n")
print(f"  {'wallet':<46} {'n':>4} {'median_net_5m':>14} {'%>0':>6} {'sign p':>8}")
print("  " + "-" * 82)
pos = 0
for w, v in sorted(rows, key=lambda kv_: -st.median(kv_[1])):
    k = sum(1 for x in v if x > 0)
    p = kv.sign_test_p(k, len(v))
    if st.median(v) > 0:
        pos += 1
    print(f"  {w[:44]:<46} {len(v):>4} {st.median(v):>13.2f}% {k/len(v)*100:>5.1f}% {p:>8.4f}")
print(f"\n  positive-median wallets: {pos} of {len(rows)}   negative: {len(rows)-pos}")

print("\n  activity rank (n signals, descending) — to test 'the positive ones are least active':")
for w, v in sorted(rows, key=lambda kv_: -len(kv_[1])):
    print(f"    {w[:20]:<22} n={len(v):<4} median={st.median(v):>+7.2f}%")

print("\n" + "-" * 78)
print("WHAT THE WRITEUP CLAIMS:")
print("  8zkgFGVZ…  n=20  +5.76%  55.0%")
print("  922M9fBT…  n=20  +1.32%  55.0%")
print("  3K7XMbqv…  n=25  -2.16%  36.0%")
print("  nQEqsdvA…  n=35  -3.20%  31.4%")
print("  HGXr65Ki…  n=29  -3.45%  37.9%")
print("  and: 'Five of six tracked wallets are net negative, and the two positive ones")
print("        are the least active'")
print("-" * 78)
