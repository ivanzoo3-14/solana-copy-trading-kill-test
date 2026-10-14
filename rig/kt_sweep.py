"""
kt_sweep.py -- the PUMP TEST.

Question: the clairvoyance bound says a perfect exit nets ~+3.2%. But you cannot sell at
the perfect moment. So can a REALISTIC rule -- take-profit at +X%, stop at -Y%, exit after
T seconds -- actually bank enough of that pop to beat friction?

This walks the recorded forward path of every signal and simulates each rule.

  python kt_sweep.py            # default grid
  python kt_sweep.py --all      # ignore the latency<=60s primary filter (diagnostic)

CAVEAT (read this): existing forwards are sampled at h=[30,60,300,900,3600,...]. A pop that
happens and dies INSIDE the first 30 seconds is invisible here, and a take-profit touched
between samples is missed. So this UNDERSTATES take-profit fills. It is a lower bound on
the pump. kt_fastpath.py exists to fix exactly that.
"""
from __future__ import annotations

import json
import os
import statistics
import sys

sys.path.insert(0, r"C:\killtest-rig")
from kt_lib import Store, load_config            # noqa: E402

TPS = [2.0, 3.0, 5.0, 8.0, 12.0]
SLS = [None, -10.0, -20.0, -40.0]
TIMEOUTS = [60, 300, 900]

# assumed realistic exit fill when a stop is hit (thin pool = worse than the stop level)
STOP_OVERSHOOT_PCT = 0.0     # 0 = assume you fill AT the stop; try 5/10 to stress it


def load_paths(store: Store, cfg: dict, primary_only: bool):
    sigs, fwds = {}, {}
    for r in store.read_signals():
        k = r.get("kind")
        if k == "signal":
            sigs[r.get("id")] = r
        elif k == "forward":
            fwds.setdefault(r.get("id"), []).append(r)

    fp_now = None
    try:
        from kt_verdict import config_fingerprint
        fp_now = config_fingerprint(cfg)
    except Exception as e:
        print(f"  (fingerprint unavailable: {e}; not filtering by version)")

    keep, seen = [], set()
    for sid, s in sigs.items():
        if fp_now and s.get("config_fp") != fp_now:
            continue
        if not s.get("usable"):
            continue
        if primary_only:
            lat = s.get("latency_sec_slot")
            if lat is None or lat > 60.0:
                continue
        key = (s.get("wallet"), s.get("mint"))
        if key in seen:                     # first-per-(wallet,mint), same as the verdict
            continue
        seen.add(key)
        path = sorted(fwds.get(sid, []), key=lambda r: r.get("h") or 0)
        if not path:
            continue
        keep.append((s, path))
    return keep


def simulate(path: list[dict], tp: float, sl: float | None, timeout: int) -> float | None:
    """
    Walk the sampled path in time order. Take-profit fills at the level (generous: it is a
    resting limit order). Stop fills at the level minus overshoot (realistic). Otherwise
    exit at the last sample at or before the timeout.
    """
    last_net = None
    for r in path:
        h = r.get("h") or 0
        net = r.get("net_pct")
        if net is None or h > timeout:
            break
        last_net = net
        if net >= tp:
            return tp                                    # limit sell filled
        if sl is not None and net <= sl:
            return sl - STOP_OVERSHOOT_PCT               # stop filled, no better
    return last_net


def main(argv: list[str]) -> int:
    cfg = load_config()
    store = Store(os.path.join(r"C:\killtest-rig", cfg.get("log_dir", "logs")))
    primary_only = "--all" not in argv
    paths = load_paths(store, cfg, primary_only)
    if not paths:
        print("no usable paths yet -- need signals with forward samples.")
        return 0

    print("=" * 96)
    print("PUMP TEST -- can a realistic rule bank the pop?   "
          f"(n={len(paths)} signals, {'primary <=60s' if primary_only else 'ALL latencies'})")
    print("=" * 96)

    # baseline: just hold to each timeout
    print("\nBASELINE -- buy and hold, no rule")
    for t in TIMEOUTS:
        vals = [v for v in (simulate(p, 1e9, None, t) for _, p in paths) if v is not None]
        if vals:
            print(f"  hold {t:>4}s : n={len(vals):>3}  mean={statistics.mean(vals):>7.2f}%  "
                  f"median={statistics.median(vals):>7.2f}%  win%={100*sum(1 for v in vals if v > 0)/len(vals):>5.1f}")

    print(f"\nRULE SWEEP   (stop overshoot assumption: {STOP_OVERSHOOT_PCT:.0f}pp)")
    print(f"  {'TP':>5} {'SL':>6} {'tout':>6} | {'n':>4} {'mean_net':>9} {'median':>8} {'win%':>6} "
          f"{'TP_hit%':>8} {'SL_hit%':>8}")
    print("  " + "-" * 74)
    best = []
    for tp in TPS:
        for sl in SLS:
            for to in TIMEOUTS:
                vals, tp_hits, sl_hits = [], 0, 0
                for _, p in paths:
                    v = simulate(p, tp, sl, to)
                    if v is None:
                        continue
                    vals.append(v)
                    if abs(v - tp) < 1e-9:
                        tp_hits += 1
                    elif sl is not None and v <= sl - STOP_OVERSHOOT_PCT + 1e-9:
                        sl_hits += 1
                if len(vals) < 20:
                    continue
                m = statistics.mean(vals)
                best.append((m, tp, sl, to, len(vals), statistics.median(vals),
                             100 * sum(1 for v in vals if v > 0) / len(vals),
                             100 * tp_hits / len(vals), 100 * sl_hits / len(vals)))
                print(f"  {tp:>5.0f} {str(sl):>6} {to:>6} | {len(vals):>4} {m:>8.2f}% "
                      f"{statistics.median(vals):>7.2f}% {100*sum(1 for v in vals if v > 0)/len(vals):>5.1f} "
                      f"{100*tp_hits/len(vals):>7.1f} {100*sl_hits/len(vals):>7.1f}")

    print("\n" + "=" * 96)
    print("TOP 5 RULES BY MEAN NET")
    print("=" * 96)
    for m, tp, sl, to, n, med, wr, tph, slh in sorted(best, reverse=True)[:5]:
        verdict = "PROFITABLE" if m > 0 else "loses"
        print(f"  TP {tp:>4.0f}%  SL {str(sl):>6}  timeout {to:>4}s   mean {m:>+6.2f}%  "
              f"median {med:>+6.2f}%  win {wr:>4.1f}%  -> {verdict}")
    print("\n  Reminder: this UNDERSTATES take-profit fills (samples start at 30s).")
    print("  If the best rule here is negative, a finer path would have to beat it by")
    print("  more than the sampling gap to matter. Run kt_fastpath.py to close that gap.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
