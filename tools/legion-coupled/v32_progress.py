"""v32_progress.py -- how far is v3.2 from its registered stopping rule, and what did the outage cost?

Reuses kt_wallets.load() itself (same dedup, same 900 s wall-latency allowance, same fp filter),
but feeds it the rig's own config.json parsed directly, so this script never calls load_config()
and therefore never opens LEGION\\config.json at all. Read-only.

  python v32_progress.py
"""
import json
import os
import statistics
import sys
import datetime as dt

sys.path.insert(0, r"C:\killtest-rig")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import kt_wallets as kw                       # noqa: E402
from kt_verdict import config_fingerprint      # noqa: E402
from kt_lib import substantive_config          # noqa: E402

KTCFG = r"C:\killtest-rig\config.json"
cfg = json.load(open(KTCFG, encoding="utf-8"))   # rig config only; contains no key material
fp = config_fingerprint(cfg)
print(f"config fingerprint from rig config.json : {fp}")
print(f"expected v3.2 fingerprint               : 63b8561732a5c6bc   "
      f"{'MATCH' if fp == '63b8561732a5c6bc' else '*** MISMATCH -- do not trust the numbers below ***'}")

rows = kw.load(cfg)
print(f"usable {kw.HORIZON}s rows (fp-filtered, deduped, wall lat <= {kw.LAT_CAP:.0f}s): {len(rows)}")
if not rows:
    sys.exit(0)

rows.sort(key=lambda r: r["ts"])
first, last = rows[0]["ts"], rows[-1]["ts"]
span_h = (last - first).total_seconds() / 3600.0
print(f"first row {first.isoformat()}   last row {last.isoformat()}   span {span_h:.2f} h")
print(f"rate since start: {len(rows)/span_h:.1f} usable rows/h")

cut = rows[int(len(rows) * 0.6)]["ts"]
train = [r for r in rows if r["ts"] < cut]
hold = [r for r in rows if r["ts"] >= cut]
print(f"\nsplit boundary {cut.isoformat()} (60/40 by time)")
print(f"  train {len(train)}   holdout {len(hold)}")


def scope(rs, tier):
    return [r for r in rs if r.get("tier") == tier] if tier else rs


def wallet_stats(rs):
    d = {}
    for r in rs:
        d.setdefault(r["wallet"], []).append(r["net"])
    return d


for label, tier, primary in (("Tier B (PRIMARY -- K is drawn here)", "B", True),
                             ("Tier A (websocket, frequency-ranked)", "A", False),
                             ("A+B union (secondary only)", None, False)):
    tr, ho = scope(train, tier), scope(hold, tier)
    d = wallet_stats(tr)
    elig = {w: v for w, v in d.items() if len(v) >= kw.MIN_TRAIN_N}
    print(f"\n{label}")
    print(f"  train rows {len(tr):<6} holdout rows {len(ho):<6} | wallets seen {len(d):<4} "
          f"eligible (train n>={kw.MIN_TRAIN_N}): {len(elig)}")
    if elig:
        ranked = sorted(elig.items(), key=lambda kv: -statistics.median(kv[1]))
        for w, v in ranked[:5]:
            hn = [x["net"] for x in ho if x["wallet"] == w]
            hs = f"{statistics.median(hn):+.2f}%" if hn else "      -"
            print(f"    {w[:44]:<46} train n={len(v):<4} med {statistics.median(v):+7.2f}%   "
                  f"holdout n={len(hn):<4} med {hs}")
    picked = sorted(elig.items(), key=lambda kv: -statistics.median(kv[1]))[:kw.TOP_K] if elig \
        else []
    sel_hold = [x["net"] for x in ho if x["wallet"] in {w for w, _ in picked}]
    print(f"  REGISTERED PASS needs holdout n>={kw.MIN_HOLDOUT_N} for the SELECTED wallets: "
          f"{len(sel_hold)} so far "
          f"({'MET' if len(sel_hold) >= kw.MIN_HOLDOUT_N else f'SHORT by {kw.MIN_HOLDOUT_N-len(sel_hold)}'})"
          f"   [all-wallet holdout rows: {len(ho)}]")

# ---- outage cost ----------------------------------------------------------------
stop = dt.datetime(2026, 10, 17, 23, 12, tzinfo=dt.timezone.utc)
now = dt.datetime.now(dt.timezone.utc)
print(f"\nregistered stop 2026-10-17 23:12Z is {((stop-now).total_seconds()/3600):.1f} h away")
rate_h = len(rows) / span_h
print(f"outage so far (last row -> now) = {(now-last).total_seconds()/3600:.2f} h "
      f"= ~{rate_h*(now-last).total_seconds()/3600:.0f} usable rows not collected")
