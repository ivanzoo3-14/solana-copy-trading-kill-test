"""tracker_queue.py -- how much catch-up work is still queued ahead of new signals?

On restart, _load_existing re-queues every v3.2 signal with `complete` false, and track() services
`pending` oldest-first at max_fetches=60 per 20 s pass (~180 fills/min). Every horizon already due
but not yet written is a fill that must happen BEFORE a newly detected signal's 300 s bar gets
serviced. This counts that work, so the "when will new signals track normally again" question has a
number instead of a shrug.

Read-only. No LEGION file is opened.
"""
import collections
import io
import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PATH = r"C:\killtest-rig\logs\signals.jsonl"
V32 = "63b8561732a5c6bc"
HORIZONS = [30, 60, 300, 900, 3600, 14400, 86400]
FILLS_PER_MIN = 60 * (60 / 20.0)          # max_fetches per pass / track_loop(every=20s)

now = time.time()
sigs, have = {}, collections.defaultdict(set)
for line in io.open(PATH, encoding="utf-8", errors="ignore"):
    if '"kind": "signal"' not in line and '"kind": "forward"' not in line:
        continue
    try:
        r = json.loads(line)
    except ValueError:
        continue
    if r.get("kind") == "signal":
        if r.get("config_fp") == V32:
            sigs[r.get("id")] = r
    else:
        have[r.get("id")].add(r.get("h"))

pending = due_total = not_due = complete = 0
for sid, s in sigs.items():
    ts = s.get("detected_at")
    if not isinstance(ts, (int, float)):
        continue
    if s.get("complete"):
        complete += 1
        continue
    elapsed = now - float(ts)
    pending += 1
    for h in HORIZONS:
        if h in have.get(sid, ()):
            continue
        if elapsed >= h:
            due_total += 1
        else:
            not_due += 1

print(f"v3.2 signals (last-wins per id)        : {len(sigs)}")
print(f"  already complete                     : {complete}")
print(f"  in the tracker's pending queue       : {pending}")
print()
print(f"fills ALREADY DUE and unwritten        : {due_total}")
print(f"fills not yet due (will come later)    : {not_due}")
print(f"tracker capacity                       : ~{FILLS_PER_MIN:.0f} fills/min "
      f"(max_fetches=60 per 20 s pass, IF every fetch succeeds)")
print(f"  -> ETA to clear the due backlog      : ~{due_total/FILLS_PER_MIN:.0f} min "
      f"at full rate; longer under 429 backoff")
print()
print("Until that drains, a newly detected signal's 300 s bar sits behind it in the queue, which is")
print("why recent signals show 0% 300 s coverage while the collector itself is healthy.")
