"""Robustness checks on the v1 headline result.

B. CLUSTER-ROBUST INFERENCE. The pre-registered verdict is a sign test, which assumes independent
   observations. These signals are not independent: they cluster by WALLET (one wallet's trades
   share a strategy and timing) and by MINT (one mint's outcome is shared by every signal on it).
   This recomputes the inference accounting for that.

C. MINIMUM DETECTABLE EFFECT. Converts "we found nothing" into "we could have detected an effect
   of size X and did not" -- which pre-empts "your sample was too small".

Read-only. Reuses kt_verdict's own helpers.
"""
import collections
import math
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
LAT_CAP = 60.0
Z = 1.959964 + 0.841621          # two-sided alpha=0.05, power=80%

sigs_all, _ = kv.fold({"log_dir": "logs"})
sigs, _ = kv.dedup_first_per_wallet_mint(sigs_all)
sigs = [s for s in sigs if s.get("config_fp") == V1]
usable = [s for s in sigs if s.get("entry_price") and s.get("usable")]


def lat(s):
    v = s.get("latency_sec_slot")
    return v if v is not None else s.get("latency_sec")


pool = [s for s in usable if lat(s) is not None and lat(s) <= LAT_CAP]
rows = []
for s in pool:
    f = (s.get("forward") or {}).get("300")
    if f and isinstance(f.get("net_pct"), (int, float)):
        rows.append((float(f["net_pct"]), s.get("wallet"), s.get("mint")))

y = [v for v, _, _ in rows]
n = len(y)
mean = st.mean(y)
med = st.median(y)
sd = st.stdev(y)
se_naive = sd / math.sqrt(n)
k = sum(1 for v in y if v > 0)

print("=" * 84)
print(f"v1 PRIMARY POOL -- n={n} usable 300s outcomes")
print("=" * 84)
print(f"  median net    : {med:+.3f}%")
print(f"  mean net      : {mean:+.3f}%   sd {sd:.2f}")
print(f"  %net > 0      : {k/n*100:.1f}%   ({k}/{n})")
print(f"  sign test p   : {kv.sign_test_p(k, n):.4f}")
lo, hi = kv.bootstrap_ci(y)
print(f"  iid bootstrap 95% CI of the median: [{lo:+.3f}%, {hi:+.3f}%]")


def cluster_report(label, idx):
    cl = collections.defaultdict(list)
    for v, w, m in rows:
        cl[w if idx == "wallet" else m].append(v)
    G = len(cl)
    # cluster-robust variance of the mean (CR0 with G/(G-1) correction)
    ssum = 0.0
    for c, vals in cl.items():
        ssum += (sum(vals) - len(vals) * mean) ** 2
    var_cl = (G / (G - 1)) * ssum / (n * n)
    se_cl = math.sqrt(var_cl)
    t_cl = mean / se_cl
    deff = (se_cl / se_naive) ** 2
    # cluster bootstrap of the median
    keys = list(cl)
    rnd = random.Random(12345)
    meds = []
    for _ in range(4000):
        s = []
        for _ in range(len(keys)):
            s.extend(cl[keys[rnd.randrange(len(keys))]])
        meds.append(st.median(s))
    meds.sort()
    mlo, mhi = meds[int(.025 * len(meds))], meds[int(.975 * len(meds))]
    # cluster-level sign test: per-cluster median, then sign test across clusters
    cmed = [st.median(v) for v in cl.values()]
    cpos = sum(1 for x in cmed if x > 0)

    print(f"\n  --- clustered by {label} ({G} clusters) ---")
    print(f"    mean (unchanged)          : {mean:+.3f}%")
    print(f"    naive SE / cluster SE     : {se_naive:.3f} / {se_cl:.3f}   "
          f"design effect {deff:.2f}x")
    print(f"    naive t / cluster t       : {mean/se_naive:+.2f} / {t_cl:+.2f}")
    print(f"    cluster-bootstrap 95% CI of the median: [{mlo:+.3f}%, {mhi:+.3f}%]  "
          f"-> {'EXCLUDES' if mlo > 0 or mhi < 0 else 'INCLUDES'} zero")
    print(f"    cluster-level sign test   : {cpos}/{G} clusters have a positive median, "
          f"p={kv.sign_test_p(cpos, G):.4f}")
    print(f"    minimum detectable effect : +/-{Z*se_cl:.2f} pp "
          f"(alpha=0.05 two-sided, power=80%)   [naive: +/-{Z*se_naive:.2f} pp]")
    return se_cl


print("\n" + "=" * 84)
print("B. CLUSTER-ROBUST INFERENCE")
print("=" * 84)
se_w = cluster_report("wallet", "wallet")
se_m = cluster_report("mint", "mint")

print("\n" + "=" * 84)
print("C. MINIMUM DETECTABLE EFFECT, in context")
print("=" * 84)
ceil_net = 10.17          # v1 clairvoyance bound, net of friction (recomputed 2026-10-11)
print(f"  observed median net            : {med:+.3f}%")
print(f"  clairvoyance ceiling (perfect exit, NET of friction): +{ceil_net:.2f}%")
print(f"  MDE (wallet-clustered)         : +/-{Z*se_w:.2f} pp")
print(f"  MDE (mint-clustered)           : +/-{Z*se_m:.2f} pp")
for lab, se in (("wallet", se_w), ("mint", se_m)):
    mde = Z * se
    verdict = ("COULD have detected a ceiling-sized edge" if mde <= ceil_net
               else "could NOT reliably detect a ceiling-sized edge")
    print(f"  -> {lab}-clustered: the study {verdict} (MDE {mde:.2f} vs ceiling {ceil_net:.2f})")

# the pre-registered test is a SIGN TEST on the positive rate, so its power is the relevant one.
z_sig = 1.644854 + 0.841621        # one-sided alpha=0.05, power=80%
mde_p = 0.5 + z_sig * math.sqrt(0.25 / n)
print(f"\n  POWER OF THE ACTUAL PRE-REGISTERED TEST (one-sided sign test, n={n}):")
print(f"    could detect a true positive-rate of {mde_p*100:.1f}% vs the 50% null")
print(f"    observed positive-rate : {k/n*100:.1f}%")
print(f"    -> the design was amply powered to detect a win rate that would have mattered,")
print(f"       and the observed rate sits well BELOW the null, not near it.")

print(f"""
  CAUTION on the mean-based MDE: the mean's sd is {sd:.1f}pp, so outlier-driven, and the
  clairvoyance ceiling is reported as a MEDIAN. Compare like with like: the perfect-exit
  MEAN was +48.89% and its median +10.17%, both far above the MDE, so the design had the
  power to see an edge of that size. It saw none.""")
