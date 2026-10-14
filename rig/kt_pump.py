"""
kt_pump.py -- the FINE-resolution pump test (closes the 30s blind spot).

kt_sweep.py used forward samples starting at h=30s, so a pop that fires and decays inside
the first 30 seconds was invisible. kt_fastpath.py sampled every 3s for 120s. This runs the
same take-profit/stop grid over that fine path.

BASIS CORRECTION: the rig's entry_price comes from a DexScreener-first source, while
fastpath samples Jupiter. Those disagree by a few percent on thin pools. So for each signal
we subtract its own first sample ("basis") from the whole path. What remains is the move
AFTER we started watching -- which is what a resting limit order would actually experience.
Cost of the correction: the first ~3 seconds of movement are excluded.

  python kt_pump.py
  python kt_pump.py --max-t 60     # only consider the first 60s
"""
from __future__ import annotations

import json
import os
import statistics
import sys

KT = r"C:\killtest-rig"
sys.path.insert(0, KT)
from kt_lib import Store, load_config            # noqa: E402

TPS = [1.0, 2.0, 3.0, 5.0, 8.0, 12.0]
SLS = [None, -5.0, -10.0, -20.0]
TIMEOUTS = [15, 30, 60, 120]
OVERSHOOT = 0.0


def current_fp(cfg) -> str | None:
    try:
        from kt_verdict import config_fingerprint
        return config_fingerprint(cfg)
    except Exception:
        return None


def load(cfg, max_t: float | None):
    store = Store(os.path.join(KT, cfg.get("log_dir", "logs")))
    fp = current_fp(cfg)

    sigs = {}
    for r in store.read_signals():
        if r.get("kind") == "signal":
            sigs[r.get("id")] = r

    paths: dict[str, list] = {}
    with open(os.path.join(store.dir, "fastpath.jsonl"), encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("t_sec") is None or o.get("ret_pct") is None:
                continue
            if max_t is not None and o["t_sec"] > max_t:
                continue
            paths.setdefault(o["id"], []).append((float(o["t_sec"]), float(o["ret_pct"])))

    out, seen = [], set()
    for sid, pts in paths.items():
        s = sigs.get(sid)
        if not s or not s.get("usable"):
            continue
        if fp and s.get("config_fp") != fp:
            continue
        lat = s.get("latency_sec_slot")
        if lat is None or lat > 60.0:
            continue
        key = (s.get("wallet"), s.get("mint"))
        if key in seen:
            continue
        seen.add(key)
        pts.sort()
        if len(pts) < 8:
            continue
        basis = pts[0][1]                      # source-basis + first-3s move
        adj = [(t, r - basis) for t, r in pts]
        out.append({"id": sid, "wallet": s.get("wallet"), "pts": adj,
                    "fric": float(s.get("friction_pct") or 0.0)})
    return out


def sim(pts, fric, tp, sl, timeout):
    last = None
    for t, r in pts:
        if t > timeout:
            break
        net = r - fric
        last = net
        if net >= tp:
            return tp, True
        if sl is not None and net <= sl:
            return sl - OVERSHOOT, False
    return (last if last is not None else 0.0), False


def main(argv):
    cfg = load_config()
    max_t = None
    if "--max-t" in argv:
        max_t = float(argv[argv.index("--max-t") + 1])
    rows = load(cfg, max_t)
    if not rows:
        print("no fastpath paths matched (need usable signals, fingerprint match, latency<=60s)")
        return 0

    print("=" * 92)
    print(f"FINE-RESOLUTION PUMP TEST   n={len(rows)} signals   "
          f"median {statistics.median(len(r['pts']) for r in rows):.0f} samples/signal"
          + (f"   window<= {max_t:.0f}s" if max_t else ""))
    print("=" * 92)

    # how often is there any fast pop at all?
    print("\nDOES A FAST POP EXIST?  (in the first 15s / 30s / 60s, net of friction)")
    for w in (15, 30, 60, 120):
        best = [max(r for t, r in p["pts"] if t <= w) - p["fric"]
                for p in rows if any(t <= w for t, _ in p["pts"])]
        if best:
            print(f"  best net within {w:>3}s : median {statistics.median(best):>+6.2f}%   "
                  f"mean {statistics.mean(best):>+6.2f}%   "
                  f">{0:>2}% in {100*sum(1 for b in best if b > 0)/len(best):>5.1f}% of signals")
    base = [r - p["fric"] for p in rows for t, r in p["pts"] if t <= 0.5]
    if base:
        print(f"\n  entry-basis check: first-sample net median {statistics.median(base):>+6.2f}% "
              f"(should be ~0 by construction; large = source disagreement)")

    print(f"\n{'TP':>5} {'SL':>6} {'tout':>6} | {'n':>4} {'mean_net':>9} {'median':>8} "
          f"{'win%':>6} {'TP_hit%':>8} {'SL_hit%':>8}")
    print("-" * 76)
    best_rows = []
    for tp in TPS:
        for sl in SLS:
            for to in TIMEOUTS:
                vals, hits, stops = [], 0, 0
                for p in rows:
                    v, hit = sim(p["pts"], p["fric"], tp, sl, to)
                    vals.append(v)
                    hits += hit
                    if sl is not None and not hit and v <= sl - OVERSHOOT + 1e-9:
                        stops += 1
                if len(vals) < 30:
                    continue
                m = statistics.mean(vals)
                best_rows.append((m, tp, sl, to, statistics.median(vals),
                                  100 * sum(1 for v in vals if v > 0) / len(vals),
                                  100 * hits / len(vals), 100 * stops / len(vals)))
                if to in (30, 120) and sl in (None, -10.0):
                    print(f"{tp:>5.0f} {str(sl):>6} {to:>6} | {len(vals):>4} {m:>8.2f}% "
                          f"{statistics.median(vals):>7.2f}% "
                          f"{100*sum(1 for v in vals if v > 0)/len(vals):>5.1f} "
                          f"{100*hits/len(vals):>7.1f} {100*stops/len(vals):>7.1f}")

    print("\n" + "=" * 92)
    print("TOP 6 BY MEAN NET")
    print("=" * 92)
    for m, tp, sl, to, med, wr, h, s in sorted(best_rows, reverse=True)[:6]:
        print(f"  TP {tp:>4.0f}%  SL {str(sl):>6}  tout {to:>4}s   mean {m:>+6.2f}%  "
              f"median {med:>+6.2f}%  win {wr:>4.1f}%  TPfill {h:>4.1f}%  "
              f"-> {'PROFITABLE' if m > 0 else 'loses'}")
    print("\n  If the best mean here is still negative, the pop is not capturable by a")
    print("  consistent rule at ANY resolution, and the copy-trade premise is closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
