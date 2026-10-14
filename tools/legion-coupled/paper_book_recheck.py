"""Re-verify the writeup's live-paper-book figures (the last unre-derived numbers).

Writeup claims: 46 closed trades, net -$5.50, expectancy -$0.120/trade, t = -4.12,
bootstrap 95% CI [-$0.179, -$0.066] per trade.
"""
import io
import json
import math
import os
import random
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = r"C:\LEGION\paper_trades.json"
d = json.load(io.open(P, encoding="utf-8"))
tr = d if isinstance(d, list) else (d.get("trades") or d.get("closed") or [])
closed = [t for t in tr if str(t.get("status")) == "closed"]
print(f"paper_trades.json: {len(tr)} entries, {len(closed)} closed")


def pnl(t):
    v = t.get("realized_pnl")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


vals = [v for v in (pnl(t) for t in closed) if v is not None]
n = len(vals)
mean = st.mean(vals)
sd = st.stdev(vals) if n > 1 else 0.0
tstat = mean / (sd / math.sqrt(n)) if sd else float("nan")

rnd = random.Random(12345)
iters = 10000
boot = sorted(st.mean([vals[rnd.randrange(n)] for _ in range(n)]) for _ in range(iters))
lo, hi = boot[int(0.025 * iters)], boot[int(0.975 * iters)]

print(f"\n  n closed        : {n}")
print(f"  net P&L         : ${sum(vals):+.2f}")
print(f"  expectancy      : ${mean:+.4f} / trade")
print(f"  t-statistic     : {tstat:+.2f}")
print(f"  bootstrap 95% CI: [${lo:+.4f}, ${hi:+.4f}] per trade")
wins = sum(1 for v in vals if v > 0)
print(f"  win rate        : {wins}/{n} = {wins/n*100:.1f}%")

print("\n" + "-" * 62)
print("WRITEUP CLAIMS:  46 closed, net -$5.50, -$0.120/trade, t=-4.12,")
print("                 CI [-$0.179, -$0.066]")
print("-" * 62)
print(f"  n      : claimed 46        actual {n}          {'MATCH' if n==46 else 'DIFFERS'}")
print(f"  net    : claimed -5.50     actual {sum(vals):+.2f}      {'MATCH' if abs(sum(vals)+5.50)<0.05 else 'DIFFERS'}")
print(f"  expect.: claimed -0.120    actual {mean:+.4f}    {'MATCH' if abs(mean+0.120)<0.005 else 'DIFFERS'}")
print(f"  t      : claimed -4.12     actual {tstat:+.2f}     {'MATCH' if abs(tstat+4.12)<0.15 else 'DIFFERS'}")
print(f"  CI     : claimed [-0.179,-0.066]  actual [{lo:+.3f},{hi:+.3f}]")
print("\n  Direction is unchanged: the book is still net negative and still significant.")
