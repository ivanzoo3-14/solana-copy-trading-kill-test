"""fwd_age_check.py -- is a forward labelled "+300s" actually taken at 300 s?

kt_run.track() writes a forward when a pass finally services a signal whose horizon has
elapsed: `if key in forward or elapsed < h: continue`. With a backlogged tracker, the
record written for h=300 can be fetched long after 300 s, while still being scored as the
300 s outcome. Each forward record carries `age_sec` (elapsed at fetch), so this is directly
measurable. Highest-value check on the v3.2 verdict, because its primary horizon is 300 s.

Read-only. No LEGION file is opened.
"""
import collections
import io
import json
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PATH = r"C:\killtest-rig\logs\signals.jsonl"
FPS = [("v1  d3753551dc57aa1b", "d3753551dc57aa1b"),
       ("v3.2 63b8561732a5c6bc", "63b8561732a5c6bc"),
       ("v3.1 6a9f1ff9c87aeea0", "6a9f1ff9c87aeea0")]

sigs, fwd = {}, collections.defaultdict(lambda: collections.defaultdict(list))
with io.open(PATH, encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        k = r.get("kind")
        if k == "signal":
            sigs[r.get("id")] = r
        elif k == "forward":
            fwd[r.get("id")][r.get("h")].append(r)

print("age_sec of the forward actually used for each horizon "
      "(age_sec > horizon means the bar was fetched late)\n")
for label, fp in FPS:
    ids = [i for i, s in sigs.items() if s.get("config_fp") == fp and s.get("usable")]
    print(f"{label}   usable signals: {len(ids)}")
    print(f"  {'h':>6} {'n':>6} {'age med':>9} {'age p90':>9} {'age max':>10} "
          f"{'late>1.2x':>10} {'late>2x':>9}  (seconds)")
    for h in (30, 60, 300, 900):
        ages = []
        for i in ids:
            for r in fwd.get(i, {}).get(h, []):
                a = r.get("age_sec")
                if isinstance(a, (int, float)):
                    ages.append(float(a))
        if not ages:
            print(f"  {h:>6} {0:>6}")
            continue
        late = sum(1 for a in ages if a > h * 1.2) / len(ages) * 100
        late2 = sum(1 for a in ages if a > h * 2) / len(ages) * 100
        print(f"  {h:>6} {len(ages):>6} {st.median(ages):>9.0f} "
              f"{sorted(ages)[int(.9*(len(ages)-1))]:>9.0f} {max(ages):>10.0f} "
              f"{late:>9.1f}% {late2:>8.1f}%")
    print()
