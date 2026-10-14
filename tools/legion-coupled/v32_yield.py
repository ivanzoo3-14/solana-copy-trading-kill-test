"""v32_yield.py -- hourly v3.2 yield: how many signals arrived, how many became USABLE rows.

`usable` requires a successful depth-based slippage quote (quote_buy_two_sizes). The rig's error log
shows thousands of Jupiter 429s, and the last usable 300 s row (16:35Z) predates the process stop
(21:13Z) by hours -- so this measures whether the usable yield collapsed before the collector died.

Read-only. Reads killtest/logs/signals.jsonl only; opens no LEGION file.
"""
import collections
import datetime as dt
import io
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

V32 = "63b8561732a5c6bc"
PATH = r"C:\killtest-rig\logs\signals.jsonl"

sigs, fwd300 = {}, set()
with io.open(PATH, encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == "signal":
            if r.get("config_fp") == V32:
                sigs[r.get("id")] = r
        elif r.get("kind") == "forward" and r.get("h") == 300:
            fwd300.add(r.get("id"))

hour = collections.defaultdict(lambda: collections.Counter())
reasons = collections.Counter()
for s in sigs.values():
    ts = s.get("detected_at")
    if not isinstance(ts, (int, float)):
        continue
    h = dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).strftime("%m-%d %HZ")
    c = hour[h]
    c["all"] += 1
    if s.get("usable"):
        c["usable"] += 1
        if s.get("id") in fwd300:
            c["usable+fwd300"] += 1
    else:
        reasons[str(s.get("unusable_reason"))[:40]] += 1

print(f"v3.2 signal records (last-wins per id): {len(sigs)}")
print(f"\n{'hour (UTC)':<12} {'signals':>8} {'usable':>8} {'usable+300s':>12} {'usable %':>9}")
print("-" * 54)
for h in sorted(hour)[-14:]:
    c = hour[h]
    pct = 100 * c["usable"] / c["all"] if c["all"] else 0
    print(f"{h:<12} {c['all']:>8} {c['usable']:>8} {c['usable+fwd300']:>12} {pct:>8.1f}%")

print("\nunusable reasons (whole v3.2 run):")
for k, v in reasons.most_common(8):
    print(f"  {v:>6}  {k}")
