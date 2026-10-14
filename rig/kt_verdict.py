"""
kt_verdict.py -- PRE-REGISTERED verdict for the kill test.

Reads logs/signals.jsonl (append-only) and applies exactly the criteria frozen in
PREREGISTRATION.md. No thresholds in this file are tunable: they are read from config
and compared literally. If you feel the urge to edit this file after seeing results,
re-read PREREGISTRATION.md section "Rules of conduct".

  python kt_verdict.py
  python kt_verdict.py --all      (ignore the latency filter; diagnostic only)
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics as st
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt_lib import HERE, Store, load_config


def sign_test_p(k: int, n: int, p0: float = 0.5) -> float:
    """One-sided P(X >= k | n, p0)."""
    if n <= 0:
        return 1.0
    return sum(math.comb(n, i) * p0 ** i * (1 - p0) ** (n - i) for i in range(k, n + 1))


def bootstrap_ci(vals: list[float], stat=st.median, iters: int = 10000, alpha: float = 0.05):
    if len(vals) < 5:
        return (None, None)
    rnd = random.Random(12345)
    n = len(vals)
    out = []
    for _ in range(iters):
        out.append(stat([vals[rnd.randrange(n)] for _ in range(n)]))
    out.sort()
    return out[int(alpha / 2 * iters)], out[int((1 - alpha / 2) * iters)]


def fold(cfg: dict) -> tuple[list[dict], dict]:
    store = Store(os.path.join(HERE, cfg.get("log_dir", "logs")))
    recs = store.read_signals()
    sigs: dict[str, dict] = {}
    order: list[str] = []
    completes: dict[str, dict] = {}
    for r in recs:
        k = r.get("kind")
        if k == "signal":
            sigs[r["id"]] = r
            order.append(r["id"])
        elif k == "forward":
            s = sigs.get(r.get("id"))
            if s is not None:
                s.setdefault("forward", {})[str(r["h"])] = r
        elif k == "complete":
            completes[r.get("id")] = r
    return [sigs[i] for i in order if i in sigs], completes


def max_excursion_pct(s: dict, completes: dict) -> float | None:
    entry = s.get("entry_price")
    if not entry:
        return None
    mx = s.get("max_price")
    c = completes.get(s.get("id"))
    if c and c.get("max_price"):
        mx = max(mx or 0, c["max_price"])
    for f in (s.get("forward") or {}).values():
        if f.get("price"):
            mx = max(mx or 0, f["price"])
    if not mx:
        return None
    return (mx / entry - 1.0) * 100.0


def config_fingerprint(cfg: dict) -> str:
    import hashlib
    from kt_lib import substantive_config
    return hashlib.sha256(
        json.dumps(substantive_config(cfg), sort_keys=True).encode()).hexdigest()[:16]


def dedup_first_per_wallet_mint(sigs: list[dict]) -> tuple[list[dict], int]:
    """
    Keep only the FIRST signal per (wallet, mint).

    Statistical necessity, not tidiness: the pre-registered test is a sign test, which
    assumes independent observations. A single wallet buying the same mint 5 times produces
    5 correlated outcomes, which would inflate n and manufacture significance. The
    pre-registration says "the FIRST buy by a tracked wallet", so this is the faithful
    reading, decided before any result was seen.
    """
    best: dict[tuple, dict] = {}
    for s in sigs:
        k = (s.get("wallet"), s.get("mint"))
        cur = best.get(k)
        if cur is None or (s.get("detected_at") or 0) < (cur.get("detected_at") or 0):
            best[k] = s
    dropped = len(sigs) - len(best)
    return list(best.values()), dropped


def main(argv: list[str]) -> int:
    cfg = load_config()
    prim_h = int(cfg["primary_horizon_sec"])
    min_n = int(cfg["min_n_for_verdict"])
    use_latency_filter = "--all" not in argv
    lat_cap = float(cfg["detection"]["max_signal_latency_sec_for_primary"])

    sigs, completes = fold(cfg)
    raw_n = len(sigs)
    sigs, dropped = dedup_first_per_wallet_mint(sigs)
    # enforce the pre-registration's "no pooling across versions" rule
    fp = config_fingerprint(cfg)
    off_version = [s for s in sigs if s.get("config_fp") != fp]
    sigs = [s for s in sigs if s.get("config_fp") == fp]
    all_sigs = [s for s in sigs if s.get("entry_price")]
    usable_all = [s for s in all_sigs if s.get("usable")]
    unusable = [s for s in all_sigs if not s.get("usable")]

    if use_latency_filter:
        # filter on SLOT-BASED latency when available (clock-independent), else wall clock
        def _lat(s):
            v = s.get("latency_sec_slot")
            return v if v is not None else s.get("latency_sec")
        primary_pool = [s for s in usable_all
                        if _lat(s) is not None and _lat(s) <= lat_cap]
    else:
        primary_pool = list(usable_all)

    def horizon_nets(pool, h):
        out = []
        for s in pool:
            f = (s.get("forward") or {}).get(str(h))
            if f and isinstance(f.get("net_pct"), (int, float)):
                out.append(float(f["net_pct"]))
        return out

    print("=" * 100)
    print("KILL TEST — PRE-REGISTERED VERDICT")
    print("=" * 100)
    print(f"preregistration version : {cfg.get('preregistration_version')}")
    print(f"config fingerprint      : {config_fingerprint(cfg)}")
    print(f"signals logged          : {raw_n}   after first-per-(wallet,mint) dedup: {len(sigs) + len(off_version)}"
          f"   (dropped {dropped} correlated repeats)")
    print(f"excluded (different config): {len(off_version)}   [pre-registration: no pooling across versions]")
    print(f"in this version         : {len(sigs)}   with entry price: {len(all_sigs)}")
    print(f"usable (measured slip)  : {len(usable_all)}   unusable: {len(unusable)}   "
          f"dropout rate: {(len(unusable)/len(all_sigs)*100 if all_sigs else 0):.1f}%")
    if unusable:
        reasons: dict[str, int] = {}
        for s in unusable:
            reasons[str(s.get("unusable_reason"))] = reasons.get(str(s.get("unusable_reason")), 0) + 1
        print(f"  dropout reasons       : {reasons}")
    print(f"primary pool (latency<={lat_cap:.0f}s): {len(primary_pool)}"
          f"{'' if use_latency_filter else '   [--all: filter disabled, DIAGNOSTIC ONLY]'}")

    lats = sorted(s["latency_sec"] for s in usable_all if s.get("latency_sec") is not None)
    lats_slot = sorted(s["latency_sec_slot"] for s in usable_all
                       if s.get("latency_sec_slot") is not None)
    if lats_slot:
        n = len(lats_slot)
        print(f"\nDETECTION LATENCY (the whole point) — SLOT-BASED, clock-independent: n={n}")
        print(f"  min={lats_slot[0]:.1f}s  median={st.median(lats_slot):.1f}s  "
              f"p90={lats_slot[int(0.9*(n-1))]:.1f}s  max={lats_slot[-1]:.1f}s")
        print(f"  (Legion's cluster signal was median 4245s / 70.75 min)")
    if lats:
        n = len(lats)
        print(f"wall-clock latency (clock-corrected): n={n} median={st.median(lats):.1f}s"
              f"   [the slot-based figure above is the trustworthy one]")
    ver = sum(1 for s in usable_all if s.get("slippage_verified"))
    if usable_all:
        print(f"\nSLIPPAGE SOURCE: {ver}/{len(usable_all)} measured against an INDEPENDENT mid "
              f"({100*ver/len(usable_all):.0f}%). The rest used Jupiter for both mid and quote,")
        print("  which forces slippage toward 0 by construction — i.e. UNDERSTATES cost and is")
        print("  GENEROUS to the thesis. A kill verdict is therefore robust; a pass is not.")

    print("\n" + "-" * 100)
    print("FORWARD RETURNS, net of measured friction (primary pool)")
    print("-" * 100)
    print(f"{'horizon':>9} {'n':>5} {'median gross%':>14} {'median net%':>12} {'% net>0':>9} {'p(one-sided)':>13}")
    for h in [int(x) for x in cfg["horizons_sec"]]:
        nets = horizon_nets(primary_pool, h)
        gross = []
        for s in primary_pool:
            f = (s.get("forward") or {}).get(str(h))
            if f and isinstance(f.get("gross_pct"), (int, float)):
                gross.append(float(f["gross_pct"]))
        if not nets:
            print(f"{h:>9} {0:>5} {'-':>14} {'-':>12} {'-':>9} {'-':>13}")
            continue
        k = sum(1 for x in nets if x > 0)
        p = sign_test_p(k, len(nets))
        print(f"{h:>9} {len(nets):>5} {st.median(gross):>14.2f} {st.median(nets):>12.2f} "
              f"{k/len(nets)*100:>8.1f}% {p:>13.4f}")

    nets5 = horizon_nets(primary_pool, prim_h)
    pairs = []
    for s in primary_pool:
        e = max_excursion_pct(s, completes)
        if e is not None:
            pairs.append((e, s))
    exc = [e for e, _ in pairs]
    exc_net = [e - float(s.get("friction_pct") or 0.0) for e, s in pairs]

    print("\n" + "-" * 100)
    print("SECONDARY DIAGNOSTIC — the clairvoyance bound")
    print("(buy at signal, sell at the best price sampled afterwards, pay friction)")
    print("-" * 100)
    if exc_net:
        lo, hi = bootstrap_ci(exc_net)
        print(f"  n={len(exc_net)}  median net max-excursion = {st.median(exc_net):+.2f}%   "
              f"%positive = {sum(1 for x in exc_net if x>0)/len(exc_net)*100:.1f}%")
        if lo is not None:
            print(f"  95% bootstrap CI of the median: [{lo:+.2f}%, {hi:+.2f}%]")
        print(f"  NOTE: max excursion is sampled at discrete horizons "
              f"({cfg['horizons_sec']}), so this is a LOWER bound on the true peak.")

    print("\n" + "-" * 100)
    print("PER-WALLET SCOREBOARD (wallets with >=10 measured signals; primary pool)")
    print("-" * 100)
    by_w: dict[str, list[float]] = {}
    for s in primary_pool:
        f = (s.get("forward") or {}).get(str(prim_h))
        if f and isinstance(f.get("net_pct"), (int, float)):
            by_w.setdefault(s["wallet"], []).append(float(f["net_pct"]))
    rows = [(w, v) for w, v in by_w.items() if len(v) >= 10]
    if not rows:
        print("  (no wallet has >=10 measured signals yet)")
    else:
        for w, v in sorted(rows, key=lambda kv: -st.median(kv[1])):
            k = sum(1 for x in v if x > 0)
            print(f"  {w[:44]:<46} n={len(v):<4} median_net_5m={st.median(v):+8.2f}%  "
                  f"%>0={k/len(v)*100:>5.1f}%  p={sign_test_p(k, len(v)):.4f}")

    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    if len(nets5) < min_n:
        print(f"INSUFFICIENT DATA — {len(nets5)}/{min_n} usable {prim_h}s outcomes.")
        print("Keep collecting. Do not read anything into the numbers above yet.")
        return 0

    med_net = st.median(nets5)
    k = sum(1 for x in nets5 if x > 0)
    p = sign_test_p(k, len(nets5))
    med_exc = st.median(exc_net) if exc_net else float("-inf")
    lo, hi = bootstrap_ci(nets5)

    crit1 = len(nets5) >= min_n
    crit2 = med_net > 0
    crit3 = p < 0.05
    print(f"  n={len(nets5)} (need >= {min_n})                     : {'PASS' if crit1 else 'FAIL'}")
    print(f"  median net {prim_h}s = {med_net:+.3f}% (need > 0)      : {'PASS' if crit2 else 'FAIL'}")
    print(f"  sign test p = {p:.4f} (need < 0.05)          : {'PASS' if crit3 else 'FAIL'}")
    if lo is not None:
        print(f"  95% CI of median net: [{lo:+.3f}%, {hi:+.3f}%]")
    print(f"  median net max-excursion = {med_exc:+.3f}%")
    print()
    if crit1 and crit2 and crit3:
        print("  >>> PASS — the fast single-wallet thesis SURVIVED the kill attempt.")
        print("      This is not yet a profitable strategy. Next: out-of-sample confirmation,")
        print("      larger n, capacity/slippage at real size, and a separate capital decision.")
    elif crit1 and med_net <= 0 and med_exc <= 0:
        print("  >>> KILL — n is sufficient, the median net return is non-positive, AND the")
        print("      clairvoyance bound is non-positive. The universe does not pay, at any speed.")
        print("      STOP. Write it down. Do not retune, do not add wallets, do not rebuild.")
    else:
        print("  >>> NOT YET DECIDED — n is sufficient but the criteria are mixed.")
        print(f"      net-median {'positive' if med_net>0 else 'non-positive'}, "
              f"sign-test {'significant' if crit3 else 'not significant'}, "
              f"clairvoyance bound {'positive' if med_exc>0 else 'non-positive'}.")
        print("      Keep collecting to the next n milestone. Do not change parameters.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
