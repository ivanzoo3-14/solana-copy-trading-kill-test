"""Re-verify the v1 rule-sweep numbers by running kt_sweep.py / kt_pump.py's OWN code paths
against the v1 fingerprint.

Neither tool can see v1 data right now: both resolve the fingerprint from the live config, which
is v3.2's. Rather than reimplement the sweep (and risk drifting from it), this monkey-patches
`kt_verdict.config_fingerprint` to return the v1 fingerprint and then calls each tool's own
`main()`. Read-only: touches no config, writes nothing, and does not disturb the running rig.

  - kt_sweep.py : coarse, forward samples from h=30s up            (MEAN net is what it ranks by)
  - kt_pump.py  : fine, 3s fastpath samples basis-adjusted         (MEDIAN/MEAN over 96 rules)
"""
import collections
import io
import json
import os
import sys

KT = r"C:\killtest-rig"
sys.path.insert(0, KT)
os.chdir(KT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

V1_FP = "d3753551dc57aa1b"

# ---- does fastpath.jsonl contain any v1-era samples at all? -----------------------------
fps = collections.Counter()
n = 0
with io.open(os.path.join(KT, "logs", "fastpath.jsonl"), encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            o = json.loads(line)
        except Exception:
            continue
        fps[str(o.get("config_fp"))] += 1
print("=== fastpath.jsonl ===")
print(f"  records: {n}")
for k, v in fps.most_common():
    print(f"    {k}  {v}")
print(f"  v1 fingerprint present: {V1_FP in fps}")
print()

import kt_verdict                                    # noqa: E402

_orig = kt_verdict.config_fingerprint
kt_verdict.config_fingerprint = lambda cfg: V1_FP    # both tools import it lazily, inside a fn
print("*** running kt_sweep.py against fingerprint", V1_FP, "***\n")
import kt_sweep                                      # noqa: E402
kt_sweep.main([])

print("\n\n*** running kt_pump.py against fingerprint", V1_FP, "***\n")
import kt_pump                                       # noqa: E402
kt_pump.main([])

kt_verdict.config_fingerprint = _orig
print("\n(restored original config_fingerprint)")
