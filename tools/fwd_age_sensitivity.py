"""fwd_age_sensitivity.py -- does the short-horizon ceiling ladder survive the late-fetch defect?

Gotcha 26: the bar scored as horizon h is fetched at a median age of 87 s (h=30), 116 s (h=60),
376 s (h=300) -- i.e. the labels are optimistic. This recomputes the published ladder twice:

  (a) as recorded        -- the number in the writeup
  (b) age-clean          -- only fills fetched within 1.2x their own horizon, so the bar really is
                            near the horizon it claims to be. A signal with no qualifying fill at any
                            h <= W drops out of (b), and its n is reported.

If the two agree in sign and rough size, the defect is presentational; if they diverge, the ladder
in the writeup needs the age-clean column instead.

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
WINDOWS = (30, 60, 300, 900, 3600)


def load():
    sigs = {}
    fwd = collections.defaultdict(lambda: collections.defaultdict(list))
    for line in io.open(PATH, encoding="utf-8", errors="ignore"):
        if '"kind": "signal"' not in line and '"kind": "forward"' not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == "signal":
            sigs[r.get("id")] = r
        else:
            fwd[r.get("id")][r.get("h")].append((r.get("gross_pct"), r.get("age_sec")))
    return sigs, fwd


def dedup(sigs, ids):
    best = {}
    for i in ids:
        s = sigs[i]
        k = (s.get("wallet"), s.get("mint"))
        cur = best.get(k)
        if cur is None or (s.get("detected_at") or 0) < (sigs[cur].get("detected_at") or 0):
            best[k] = i
    return list(best.values())


sigs, fwd = load()
all_ids = list(sigs)
v1_ded = dedup(sigs, all_ids)
v1_pool = [sigs[i] for i in v1_ded if sigs[i].get("config_fp") == V1 and sigs[i].get("usable")
           and (sigs[i].get("latency_sec_slot") if sigs[i].get("latency_sec_slot") is not None
                else sigs[i].get("latency_sec")) is not None
           and (sigs[i].get("latency_sec_slot") if sigs[i].get("latency_sec_slot") is not None
                else sigs[i].get("latency_sec")) <= 60.0]
all_pool = [sigs[i] for i in v1_ded if sigs[i].get("usable")]

for label, pool in (("v1 primary (n=%d)" % len(v1_pool), v1_pool),
                    ("ALL usable (n=%d)" % len(all_pool), all_pool)):
    print("=" * 108)
    print(f"{label}   ceiling = max gross over h<=W, minus that signal's own friction_pct")
    print("=" * 108)
    print(f"  {'W':>6} | {'as recorded: n':>14} {'median':>8} {'>0':>6} | "
          f"{'age-clean: n':>13} {'median':>8} {'>0':>6} | {'dropped':>8}")
    for W in WINDOWS:
        rec, clean = [], []
        for s in pool:
            fr = float(s.get("friction_pct") or 0.0)
            best_rec = best_clean = None
            for h, fills in fwd.get(s["id"], {}).items():
                if h > W:
                    continue
                for g, a in fills:
                    if not isinstance(g, (int, float)):
                        continue
                    best_rec = float(g) if best_rec is None else max(best_rec, float(g))
                    if isinstance(a, (int, float)) and a <= h * 1.2:
                        best_clean = float(g) if best_clean is None else max(best_clean, float(g))
            if best_rec is not None:
                rec.append(best_rec - fr)
            if best_clean is not None:
                clean.append(best_clean - fr)
        if not rec:
            continue
        def f(v):
            if not v:
                return "-", "-"
            return (f"{st.median(v):>8.2f}%",
                    f"{100*sum(1 for x in v if x>0)/len(v):>5.1f}%")
        rm, rp = f(rec)
        cm, cp = f(clean)
        print(f"  {W:>6} | {len(rec):>14} {rm} {rp} | {len(clean):>13} {cm} {cp} | "
              f"{len(rec)-len(clean):>8}")
    print()

print("Reading: the age-clean column keeps only fills fetched within 1.2x their horizon, so its n is")
print("smaller and it drops the signals whose bars are all late. If sign and magnitude agree, the")
print("late-fetch defect is presentational and the published ladder stands.")
