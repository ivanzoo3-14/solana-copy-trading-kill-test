"""Re-verify the writeup's "event study" numbers.

Source turns out to be LEGION's own signal_tracker.py (NOT the kill-test rig): it tracks
copy_signals.json over horizons 1h/6h/24h/3d/7d/14d into signal_tracker_state.json.
Replicates _horizon_pct() = (price_at_h - entry)/entry*100, read-only.

Nothing is executed from LEGION and no state file is written.
"""
import io
import json
import os
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = r"C:\LEGION\signal_tracker_state.json"
state = json.load(io.open(P, encoding="utf-8"))
tracked = state.get("tracked", [])
print(f"signal_tracker_state.json: {len(tracked)} tracked signals\n")


def hpct(t, label):
    """kt: exact replica of signal_tracker._horizon_pct"""
    v = (t.get("prices") or {}).get(label)
    if v is None or v == "MISSED":
        return None
    try:
        return (float(v) - t["entry_price"]) / t["entry_price"] * 100.0
    except Exception:
        return None


LABELS = ["1h", "6h", "24h", "3d", "7d", "14d"]
print(f"{'horizon':>8} {'n':>6} {'median':>10} {'mean':>10} {'%>0':>7}")
print("-" * 46)
res = {}
for lab in LABELS:
    vals = [v for v in (hpct(t, lab) for t in tracked) if v is not None]
    if not vals:
        print(f"{lab:>8} {'-':>6}")
        continue
    res[lab] = vals
    k = sum(1 for x in vals if x > 0)
    print(f"{lab:>8} {len(vals):>6} {st.median(vals):>9.2f}% {st.mean(vals):>9.2f}% {k/len(vals)*100:>6.1f}%")

# vintage
ts = sorted(t.get("entry_ts") or 0 for t in tracked if t.get("entry_ts"))
if ts:
    import datetime as dt
    f = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"\nentry_ts range: {f(ts[0])}Z  ->  {f(ts[-1])}Z")

print("\n" + "-" * 60)
print("WHAT THE WRITEUP CLAIMS (2,380 tracked signals):")
print("   -8.2% (1h)   -35.6% (6h)   -62.7% (24h)   -87.6% (7d)")
print("-" * 60)
for lab, claim in (("1h", -8.2), ("6h", -35.6), ("24h", -62.7), ("7d", -87.6)):
    if lab in res:
        got = st.median(res[lab])
        flag = "MATCH" if abs(got - claim) < 0.15 else f"DIFFERS by {got-claim:+.2f}pp"
        print(f"  {lab:>4}: claimed {claim:>7.1f}%   recomputed {got:>7.2f}%   -> {flag}")

# does print_summary even emit these? it emits expectancy, not per-horizon medians
print("\nNOTE: signal_tracker.print_summary() emits win-rate / avg-win / avg-loss / expectancy,")
print("      NOT per-horizon medians. These medians were computed ad hoc, not by that script.")
