"""
kt_runners.py -- can this signal set EVER catch a runner?

"Runner" = a mint that goes 2x, 5x, 10x after the signal. This measures the best multiple
each signal actually reached (gross, before friction -- the ceiling), across every recorded
horizon, and reports how often large multiples occur at all.

If nothing reaches 5x, then no amount of extra wallet tracking changes the payoff, because
tracking changes WHICH signals you see, not what the mints DO afterwards.

  python kt_runners.py
  python kt_runners.py --by-wallet
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict

KT = r"C:\killtest-rig"
sys.path.insert(0, KT)
from kt_lib import Store, load_config            # noqa: E402

BARS = [1.5, 2.0, 3.0, 5.0, 10.0]


def load(cfg):
    store = Store(os.path.join(KT, cfg.get("log_dir", "logs")))
    fp = None
    try:
        from kt_verdict import config_fingerprint
        fp = config_fingerprint(cfg)
    except Exception:
        pass

    sigs, best = {}, defaultdict(float)
    sigfile = os.path.join(store.dir, "signals.jsonl")
    with open(sigfile, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = r.get("kind")
            if k == "signal":
                sigs[r.get("id")] = r
            elif k == "forward":
                g = r.get("gross_pct")
                if g is not None and r.get("id"):
                    best[r["id"]] = max(best[r["id"]], float(g))

    rows, seen = [], set()
    for sid, s in sigs.items():
        if not s.get("usable") or (fp and s.get("config_fp") != fp):
            continue
        if sid not in best:
            continue
        key = (s.get("wallet"), s.get("mint"))
        if key in seen:
            continue
        seen.add(key)
        rows.append({"wallet": s.get("wallet"), "mint": s.get("mint"),
                     "peak_gross": best[sid], "mult": 1 + best[sid] / 100.0,
                     "lat": s.get("latency_sec_slot")})
    return rows


def main(argv):
    cfg = load_config()
    rows = load(cfg)
    if not rows:
        print("no usable signals with forward data")
        return 0

    peaks = sorted(r["peak_gross"] for r in rows)
    mults = [r["mult"] for r in rows]
    print("=" * 88)
    print(f"RUNNER FREQUENCY   n={len(rows)} deduped signals with forward data")
    print("=" * 88)
    print(f"  peak gross return: median {statistics.median(peaks):+.2f}%   "
          f"mean {statistics.mean(peaks):+.2f}%   max {max(peaks):+.2f}%")
    print(f"  median peak multiple: {statistics.median(mults):.3f}x")
    print(f"\n  {'multiple reached':<22} {'count':>7} {'pct':>8}")
    print("  " + "-" * 40)
    for b in BARS:
        c = sum(1 for m in mults if m >= b)
        print(f"  >={b:<19.1f}x {c:>7} {100*c/len(mults):>7.1f}%")
    c2 = sum(1 for m in mults if m >= 2.0)
    print(f"\n  best single signal: {max(mults):.2f}x")

    if "--by-wallet" in argv:
        w = defaultdict(list)
        for r in rows:
            w[r["wallet"]].append(r["mult"])
        print(f"\n  {'wallet':<46} {'n':>4} {'median peak':>12} {'best':>8} {'>=2x':>6}")
        print("  " + "-" * 80)
        for wal in sorted(w, key=lambda x: -statistics.median(w[x])):
            v = w[wal]
            print(f"  {wal[:44]:<46} {len(v):>4} {statistics.median(v):>11.3f}x "
                  f"{max(v):>7.2f}x {sum(1 for x in v if x >= 2.0):>6}")

    print("\n" + "=" * 88)
    print("READING THIS")
    print("=" * 88)
    if sum(1 for m in mults if m >= 5.0) == 0:
        print("  NOTHING reached 5x. Extra wallet tracking changes which signals you see,")
        print("  not what the mints do afterwards. A larger universe reprices the same")
        print("  distribution -- it does not manufacture runners.")
    else:
        print("  Some 5x+ events exist. Check --by-wallet for whether any wallet")
        print("  concentrates them; that is the only version where selection could matter.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
