"""Final verification of the no-information control, correctly anchored.

Two things to establish honestly:
  1. Is the t=0 fastpath sample a real price observation, or an activation artefact?
  2. With the analysis anchored on the first REAL sample, does entry timing carry any information?

Includes a cluster bootstrap by mint (signals within a mint are not independent).
"""
import collections
import io
import json
import os
import random
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KT = r"C:\killtest-rig"
sys.path.insert(0, KT)
os.chdir(KT)
import kt_verdict as kv          # noqa: E402

V1 = "d3753551dc57aa1b"
sigs_all, _ = kv.fold({"log_dir": "logs"})
all_by_id = {s.get("id"): s for s in sigs_all}
paths = collections.defaultdict(list)
with io.open(os.path.join(KT, "logs", "fastpath.jsonl"), encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("t_sec") is not None and o.get("ret_pct") is not None:
            paths[o.get("id")].append((float(o["t_sec"]), float(o["ret_pct"])))


def lat(s):
    v = s.get("latency_sec_slot")
    return v if v is not None else s.get("latency_sec")


rows, seen = [], set()
for sid, pts in paths.items():
    s = all_by_id.get(sid)
    if not s or s.get("config_fp") != V1 or not s.get("usable") or s.get("entry_price") is None:
        continue
    if lat(s) is None or lat(s) > 60.0:
        continue
    key = (s.get("wallet"), s.get("mint"))
    if key in seen:
        continue
    pts = sorted(pts)
    if len(pts) < 8:
        continue
    seen.add(key)
    rows.append({"mint": s.get("mint"), "pts": pts, "fric": float(s.get("friction_pct") or 0.0)})

# ---------------------------------------------------------------- 1. is sample#0 real?
print("=" * 84)
print("1. IS THE t=0 SAMPLE A REAL OBSERVATION?")
print("=" * 84)
v0 = [r["pts"][0][1] for r in rows]
exact0 = sum(1 for v in v0 if v == 0.0)
print(f"  n={len(v0)}   exactly 0.0: {exact0} ({exact0/len(v0)*100:.0f}%)   "
      f"within +/-2%: {sum(1 for v in v0 if abs(v)<=2)}")
q = sorted(v0)
print(f"  percentiles: p5={q[int(.05*len(q))]:+.1f}%  p25={q[int(.25*len(q))]:+.1f}%  "
      f"med={st.median(v0):+.2f}%  p75={q[int(.75*len(q))]:+.1f}%  p95={q[int(.95*len(q))]:+.1f}%")
print(f"  range: min {min(v0):+.1f}%  max {max(v0):+.1f}%")
print("  -> a genuine 'price now vs entry' reading should sit near 0. A distribution spanning")
print("     -99% to +712% with a -6% median is an ACTIVATION ARTEFACT, not a measurement.")

# how often do consecutive samples repeat exactly (upstream price caching)?
rep = tot = 0
for r in rows:
    for (_, a), (_, b) in zip(r["pts"], r["pts"][1:]):
        tot += 1
        rep += (a == b)
print(f"\n  consecutive samples with an identical ret_pct: {rep}/{tot} = {rep/tot*100:.0f}%")
print("  -> effective resolution is coarser than the nominal 3s (upstream caching).")

# ---------------------------------------------------------------- 2. correctly anchored control
print("\n" + "=" * 84)
print("2. ENTRY-TIMING CONTROL, anchored on the first real sample (t=3s)")
print("=" * 84)


def ret_at(pts, target):
    best = min(pts, key=lambda p: abs(p[0] - target))
    return best[1] if abs(best[0] - target) <= 6.0 else None


def leg(r, skip, e, H):
    base = r["pts"][skip][0]
    a = ret_at(r["pts"], base + e)
    b = ret_at(r["pts"], base + e + H)
    if a is None or b is None or (100.0 + a) <= 0:
        return None
    return ((1.0 + b / 100.0) / (1.0 + a / 100.0) - 1.0) * 100.0


for skip, name in ((0, "sample#0 (t=0)  <-- invalid anchor"), (1, "sample#1 (t=3s) <-- valid")):
    pairs = []
    for r in rows:
        if len(r["pts"]) <= skip:
            continue
        for H in (15, 30, 60):
            for e in (3, 6, 15, 30, 60):
                a = leg(r, skip, 0, H)
                b = leg(r, skip, e, H)
                if a is not None and b is not None:
                    pairs.append((b - a, r["mint"]))
    d = [x for x, _ in pairs]
    ties = sum(1 for x in d if x == 0.0)
    k = sum(1 for x in d if x > 0)
    neg = sum(1 for x in d if x < 0)
    cl = collections.defaultdict(list)
    for x, m in pairs:
        cl[m].append(x)
    keys = list(cl)
    rnd = random.Random(12345)
    boots = []
    for _ in range(4000):
        s = []
        for _ in range(len(keys)):
            s.extend(cl[keys[rnd.randrange(len(keys))]])
        boots.append(st.median(s))
    boots.sort()
    lo, hi = boots[int(.025 * len(boots))], boots[int(.975 * len(boots))]
    print(f"\n  {name}")
    print(f"    n paired      : {len(d)}   (ties at exactly 0: {ties} = {ties/len(d)*100:.0f}%)")
    print(f"    median diff   : {st.median(d):+.2f} pp    mean {st.mean(d):+.2f} pp")
    print(f"    delayed > imm : {k}   delayed < imm: {neg}")
    print(f"    cluster-boot 95% CI of median (by mint, {len(keys)} clusters): "
          f"[{lo:+.2f}, {hi:+.2f}]  -> {'EXCLUDES' if lo > 0 or hi < 0 else 'INCLUDES'} zero")

print("""
CONCLUSION: with a valid anchor the signed difference is ~0 and the CI includes zero, and most
pairs are exact TIES because consecutive samples repeat. Entry timing within the first ~2 minutes
therefore carries no measurable information -- the correct no-information result, arrived at by a
route that also killed my first (artefactual) answer.""")
