"""
kt_portfolio.py -- does the lottery-shaped payoff actually pay, as a portfolio?

The v1 pre-registration tested "is the MEDIAN net return positive?" That is the wrong
question for a fat-tailed payoff: median peak +10%, MEAN peak +57%. A take-profit rule caps
the winners and keeps the losers, which is why every TP/SL grid lost.

The right question: across many small positions with UNCAPPED upside, is portfolio
expectancy positive after friction -- and can a small bankroll survive the variance?

Reports:
  1. MEAN net return per horizon (with bootstrap CI) -- the statistic that matters
  2. Concentration: what share of total return comes from the top 1/5/10 signals
  3. Ruin simulation: fixed-$ positions from a real bankroll, uncapped hold
  4. Comparison of position sizes

  python kt_portfolio.py
  python kt_portfolio.py --bankroll 52 --size 1.5 --positions 30
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
from collections import defaultdict

KT = r"C:\killtest-rig"
sys.path.insert(0, KT)
from kt_lib import Store, load_config            # noqa: E402

HORIZONS = [300, 900, 3600, 14400]


def load(cfg):
    store = Store(os.path.join(KT, cfg.get("log_dir", "logs")))
    fp = None
    try:
        from kt_verdict import config_fingerprint
        fp = config_fingerprint(cfg)
    except Exception:
        pass

    sigs = {}
    fwd = defaultdict(dict)                 # id -> {h: net_pct}
    with open(os.path.join(store.dir, "signals.jsonl"), encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = r.get("kind")
            if k == "signal":
                sigs[r.get("id")] = r
            elif k == "forward":
                if r.get("id") and r.get("h") is not None and r.get("net_pct") is not None:
                    fwd[r["id"]][int(r["h"])] = float(r["net_pct"])

    seen, rows = set(), []
    for sid, s in sigs.items():
        if not s.get("usable") or (fp and s.get("config_fp") != fp):
            continue
        lat = s.get("latency_sec_slot")
        if lat is None or lat > 60.0:
            continue
        key = (s.get("wallet"), s.get("mint"))
        if key in seen or sid not in fwd:
            continue
        seen.add(key)
        rows.append({"wallet": s.get("wallet"), "net": fwd[sid]})
    return rows


def boot_mean(v, n=4000, seed=7):
    rnd = random.Random(seed)
    k = len(v)
    if k < 5:
        return (None, None)
    ms = []
    for _ in range(n):
        ms.append(sum(v[rnd.randrange(k)] for _ in range(k)) / k)
    ms.sort()
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def simulate(vals, bankroll, size, positions, trials=4000, seed=11):
    rnd = random.Random(seed)
    finals, ruins = [], 0
    max_afford = int(bankroll / size) if size > 0 else 0
    n = min(positions, max_afford, len(vals)) if vals else 0
    if n == 0:
        return None
    for _ in range(trials):
        bank = bankroll
        for _ in range(n):
            if bank < size:
                break
            bank -= size
            bank += size * (1.0 + vals[rnd.randrange(len(vals))] / 100.0)
        finals.append(bank)
        if bank < bankroll * 0.4:          # "ruin" = lost 60%+ of bankroll
            ruins += 1
    finals.sort()
    return {
        "n_positions": n, "median": finals[len(finals) // 2],
        "p05": finals[int(0.05 * trials)], "p95": finals[int(0.95 * trials)],
        "mean": statistics.mean(finals), "best": finals[-1], "worst": finals[0],
        "p_profit": sum(1 for f in finals if f > bankroll) / trials * 100,
        "p_ruin": ruins / trials * 100,
    }


def main(argv):
    def arg(name, dflt):
        return float(argv[argv.index(name) + 1]) if name in argv else dflt

    bankroll = arg("--bankroll", 52.0)
    size = arg("--size", 1.5)
    positions = int(arg("--positions", 30))

    cfg = load_config()
    rows = load(cfg)
    if not rows:
        print("no usable signals with forward data")
        return 0

    print("=" * 92)
    print(f"PORTFOLIO EXPECTANCY   n={len(rows)} deduped signals, latency<=60s")
    print("=" * 92)

    print(f"\n  {'horizon':>9} {'n':>5} {'MEAN net':>10} {'95% CI of mean':>22} "
          f"{'median':>9} {'%>0':>6}")
    print("  " + "-" * 72)
    series = {}
    for h in HORIZONS:
        v = [r["net"][h] for r in rows if h in r["net"]]
        if len(v) < 20:
            continue
        series[h] = v
        lo, hi = boot_mean(v)
        ci = f"[{lo:+.1f}%, {hi:+.1f}%]" if lo is not None else "-"
        print(f"  {h:>8}s {len(v):>5} {statistics.mean(v):>9.2f}% {ci:>22} "
              f"{statistics.median(v):>8.2f}% "
              f"{100*sum(1 for x in v if x > 0)/len(v):>5.1f}%")

    # concentration: is the mean carried by a handful of signals?
    print("\n  CONCENTRATION OF RETURN  (share of total net return from the biggest winners)")
    print(f"  {'horizon':>9} {'total':>10} {'top 1':>8} {'top 5':>8} {'top 10':>8} "
          f"{'rest':>8} {'mean w/o top10':>16}")
    print("  " + "-" * 74)
    for h, v in series.items():
        s = sorted(v, reverse=True)
        tot = sum(s)
        if abs(tot) < 1e-9:
            continue
        rest = s[10:]
        mw = statistics.mean(rest) if rest else 0.0
        print(f"  {h:>8}s {tot:>9.0f}% {100*sum(s[:1])/tot:>7.1f}% "
              f"{100*sum(s[:5])/tot:>7.1f}% {100*sum(s[:10])/tot:>7.1f}% "
              f"{100*sum(rest)/tot:>7.1f}% {mw:>15.2f}%")

    print(f"\n  RUIN SIMULATION   bankroll ${bankroll:.2f}, fixed position, uncapped hold")
    print(f"  {'horizon':>9} {'size':>6} {'pos':>5} {'median':>9} {'p05':>8} {'p95':>9} "
          f"{'P(profit)':>10} {'P(ruin)':>8}")
    print("  " + "-" * 74)
    for h in (3600, 14400):
        v = series.get(h)
        if not v:
            continue
        for sz in (1.0, 1.5, 2.5):
            r = simulate(v, bankroll, sz, positions)
            if not r:
                continue
            print(f"  {h:>8}s {sz:>6.2f} {r['n_positions']:>5} {r['median']:>8.2f} "
                  f"{r['p05']:>7.2f} {r['p95']:>8.2f} {r['p_profit']:>9.1f}% "
                  f"{r['p_ruin']:>7.1f}%")

    print("\n" + "=" * 92)
    print("VERDICT")
    print("=" * 92)
    long_h = 14400 if 14400 in series else (3600 if 3600 in series else None)
    if long_h is None:
        print("  INSUFFICIENT DATA -- no long-horizon forward returns yet.")
        return 0
    v = series[long_h]
    lo, hi = boot_mean(v)
    m = statistics.mean(v)
    print(f"  at {long_h}s: MEAN net {m:+.2f}%   CI [{lo:+.1f}%, {hi:+.1f}%]   "
          f"median {statistics.median(v):+.2f}%")
    if lo is not None and lo > 0:
        print("  MEAN IS POSITIVE with a CI excluding zero.")
        print("  -> A lottery-shaped portfolio has positive expectancy. The v1 verdict's")
        print("     median criterion was the wrong instrument for this payoff.")
        print("  -> NOT a licence to trade: check P(ruin) above and the concentration table.")
        print("     If the mean rests on <10 signals, it will not replicate.")
    elif m > 0:
        print("  Mean is positive but the CI INCLUDES zero -- the estimate rests on a few")
        print("  outliers. Not established. More data needed, not a strategy.")
    else:
        print("  MEAN IS NEGATIVE. The payoff does not pay as a portfolio either.")
        print("  -> This closes the line of work: not a criterion artefact, genuinely no edge.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
