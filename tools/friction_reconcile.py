"""friction_reconcile.py -- the writeup claims "~1.05-1.13% per side". Does the data say that?

The published friction line is load-bearing for the whole honest-cost argument, so it needs to be
reproducible. This dumps the actual distribution of the recorded per-side slippage and the resulting
round-trip friction, so the claim can be checked instead of repeated.

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
V1 = "d3753551dc57aa1b"
V32 = "63b8561732a5c6bc"


def q(v, p):
    v = sorted(v)
    return v[int(p * (len(v) - 1))]


sigs = {}
for line in io.open(PATH, encoding="utf-8", errors="ignore"):
    if '"kind": "signal"' not in line:
        continue
    try:
        r = json.loads(line)
    except ValueError:
        continue
    sigs[r.get("id")] = r


def dedup(ids):
    best = {}
    for i in ids:
        s = sigs[i]
        k = (s.get("wallet"), s.get("mint"))
        cur = best.get(k)
        if cur is None or (s.get("detected_at") or 0) < (sigs[cur].get("detected_at") or 0):
            best[k] = i
    return list(best.values())


allids = list(sigs)
for label, pred, lat_field in (
        ("v1 primary (slot lat<=60s, usable)", lambda s: s.get("config_fp") == V1, "slot"),
        ("v3.2 (wall lat<=900s, usable)", lambda s: s.get("config_fp") == V32, "wall"),
        ("ALL usable", lambda s: True, "wall")):
    ids = dedup([i for i in allids if pred(sigs[i]) and sigs[i].get("usable")])
    if lat_field == "slot":
        keep = []
        for i in ids:
            s = sigs[i]
            v = s.get("latency_sec_slot")
            v = s.get("latency_sec") if v is None else v
            if v is not None and v <= 60.0:
                keep.append(i)
        ids = keep
    else:
        keep = []
        for i in ids:
            s = sigs[i]
            v = s.get("latency_sec")
            v = s.get("latency_sec_slot") if v is None else v
            if v is not None and v <= 900.0:
                keep.append(i)
        ids = keep

    slip = [float(sigs[i]["slippage_pct_per_side"]) for i in ids
            if isinstance(sigs[i].get("slippage_pct_per_side"), (int, float))]
    fr = [float(sigs[i]["friction_pct"]) for i in ids
          if isinstance(sigs[i].get("friction_pct"), (int, float))]
    if not slip:
        continue
    print("=" * 100)
    print(f"{label}   n={len(slip)}")
    print(f"  per-side slippage : med {st.median(slip):.2f}%  mean {st.mean(slip):.2f}%  "
          f"p25 {q(slip,.25):.2f}%  p75 {q(slip,.75):.2f}%  p90 {q(slip,.90):.2f}%  "
          f"p99 {q(slip,.99):.2f}%  max {max(slip):.1f}%")
    print(f"  round-trip friction: med {st.median(fr):.2f}%  mean {st.mean(fr):.2f}%  "
          f"p75 {q(fr,.75):.2f}%  p90 {q(fr,.90):.2f}%")
    # which summary statistic could produce the published "1.05-1.13% per side"?
    cands = {"mean": st.mean(slip), "median": st.median(slip), "p75": q(slip, .75),
             "p80": q(slip, .80), "trimmed mean (5%)": st.mean(sorted(slip)[int(.05*len(slip)):int(.95*len(slip))])}
    for k, v in cands.items():
        flag = "   <-- matches the published claim" if 1.00 <= v <= 1.20 else ""
        print(f"    {k:>20} = {v:.2f}%{flag}")
    print()
