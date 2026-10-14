"""
kt_wallets.py -- does wallet SELECTION carry information? (PREREGISTRATION_v3)

Ranks wallets on a TRAINING window, then evaluates the winners on a later HOLDOUT window
they were never selected on. That time split is the whole design: ranking on returns and
reporting the best is guaranteed to find a winner by chance, and the holdout is what makes
the result meaningful.

  python kt_wallets.py              # run the v3 verdict (inconclusive until enough data)
  python kt_wallets.py --split 0.6  # training fraction (default 0.6; must not be tuned)
  python kt_wallets.py --explore    # show ALL wallets' train+holdout (diagnostic, no verdict)

Reads only logs/signals.jsonl. No credentials, no network.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timezone

KT = r"C:\killtest-rig"
sys.path.insert(0, KT)
from kt_lib import Store, load_config            # noqa: E402

HORIZON = 300
MIN_TRAIN_N = 25
TOP_K = 5
MIN_HOLDOUT_N = 100
# Set from config by load(). v3's registered allowance is 900s (PREREGISTRATION_v3.md
# amendment v3.1). v1's was 60s. This was hard-coded to 60.0 -- see load().
LAT_CAP = 900.0


def sign_p(k: int, n: int) -> float:
    """One-sided exact sign test: P(X >= k | p=0.5)."""
    if n <= 0:
        return 1.0
    from math import comb
    return sum(comb(n, i) for i in range(k, n + 1)) / (2.0 ** n)


def load(cfg):
    store = Store(os.path.join(KT, cfg.get("log_dir", "logs")))
    fp = None
    try:
        from kt_verdict import config_fingerprint
        fp = config_fingerprint(cfg)
    except Exception:
        pass

    sigs, fwd = {}, {}
    # read the raw file: Store.read_signals() returns only kind=="signal", so forward
    # records (a separate line kind) never load through it
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
            elif k == "forward" and r.get("h") == HORIZON:
                fwd[r.get("id")] = r.get("net_pct")

    rows, seen = [], set()
    # v3.2: the allowance comes from config. This filter used to read `lat > 60.0`, a
    # hard-coded literal carrying the v1 rule into the v3 verdict, where the registered
    # allowance is 900s. Measured on live data it kept 100% of Tier A and deleted 59% of
    # Tier B -- silently evaluating the frequency-ranked tier that amendment v3.1 created
    # Tier B to get away from. It never read config, so no config change could have fixed it.
    global LAT_CAP
    LAT_CAP = float((cfg.get("detection") or {}).get("max_signal_latency_sec_for_v3", 900.0))
    for sid, s in sigs.items():
        if not s.get("usable") or fp and s.get("config_fp") != fp:
            continue
        # v3.2: gate on WALL latency -- the same measure the ingest gate uses -- so a signal
        # the collector admitted cannot be silently deleted again here.
        #
        # This previously read latency_sec_slot, which was inflated ~1.84x by a hard-coded
        # 0.4 s/slot (measured: 0.218 s/slot) AND absorbed ingest's own processing time,
        # because ingest fetches getSlot after its price lookups. Applied to the 60s literal,
        # that combination is what deleted 59% of Tier B and 0% of Tier A.
        # latency_sec_slot is retained only as a fallback for records with no wall figure.
        lat = s.get("latency_sec")
        if lat is None:
            lat = s.get("latency_sec_slot")
        if lat is None or lat > LAT_CAP:
            continue
        key = (s.get("wallet"), s.get("mint"))
        if key in seen:
            continue
        seen.add(key)
        net = fwd.get(sid)
        raw_ts = s.get("detected_at")
        if net is None or raw_ts is None:
            continue
        try:
            # detected_at is a numeric epoch float in these records, not an ISO string
            if isinstance(raw_ts, (int, float)):
                ts = datetime.fromtimestamp(float(raw_ts), timezone.utc)
            else:
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except Exception:
            continue
        rows.append({"wallet": s.get("wallet"), "net": float(net), "ts": ts,
                     "tier": s.get("tier")})
    rows.sort(key=lambda r: r["ts"])
    return rows


def stats(v):
    if not v:
        return None
    return {"n": len(v), "median": statistics.median(v),
            "mean": statistics.mean(v),
            "pos": sum(1 for x in v if x > 0) / len(v) * 100}


def main(argv):
    cfg = load_config()
    frac = 0.6
    if "--split" in argv:
        frac = float(argv[argv.index("--split") + 1])
    rows = load(cfg)
    if len(rows) < 50:
        print(f"only {len(rows)} usable {HORIZON}s rows -- need substantially more.")
        print("expand the wallet universe and collect before running the v3 verdict.")
        return 0

    cut = rows[int(len(rows) * frac)]["ts"]
    train = [r for r in rows if r["ts"] < cut]
    hold = [r for r in rows if r["ts"] >= cut]

    print("=" * 90)
    print(f"PREREGISTRATION v3.2 -- out-of-sample wallet selection   (horizon {HORIZON}s)")
    print("=" * 90)
    print(f"  latency allowance : {LAT_CAP:.0f}s   "
          f"(v3 rule; v1's was 60s -- do not repoint at v1)")
    print(f"  total usable rows : {len(rows)}")
    print(f"  split boundary    : {cut.isoformat()}  ({frac:.0%} / {1-frac:.0%} by time)")
    print(f"  train rows        : {len(train)}    holdout rows: {len(hold)}")

    def by_wallet(rs):
        d = {}
        for r in rs:
            d.setdefault(r["wallet"], []).append(r["net"])
        return {w: stats(v) for w, v in d.items()}

    tr, ho = by_wallet(train), by_wallet(hold)

    if "--explore" in argv:
        print(f"\n  {'wallet':<46} {'train n':>8} {'tr med':>8} | {'hold n':>7} {'ho med':>8}")
        print("  " + "-" * 82)
        for w in sorted(tr, key=lambda x: -(tr[x]["median"])):
            t, h = tr[w], ho.get(w)
            hs = f"{h['median']:>7.2f}%" if h else "       -"
            hn = f"{h['n']:>7}" if h else "      -"
            print(f"  {w[:44]:<46} {t['n']:>8} {t['median']:>7.2f}% | {hn} {hs}")
        return 0

    # ---- tier census ------------------------------------------------------------
    cen = "   ".join(f"Tier {t}: {sum(1 for r in rows if r.get('tier') == t)}"
                     for t in ("A", "B"))
    print(f"\n  usable-row census:   {cen}   "
          f"untagged: {sum(1 for r in rows if r.get('tier') not in ('A', 'B'))}")

    def scope_rows(rs, tier):
        return [r for r in rs if r.get("tier") == tier] if tier else rs

    def analyse(rs_train, rs_hold, label, is_primary):
        """Selection + holdout verdict for one row set. Returns a result dict, or None."""
        tr, ho = by_wallet(rs_train), by_wallet(rs_hold)
        print("\n" + "=" * 90)
        print(label + ("   <-- PRIMARY VERDICT" if is_primary
                       else "   (secondary, not the verdict)"))
        print("=" * 90)
        eligible = {w: s for w, s in tr.items() if s["n"] >= MIN_TRAIN_N}
        if not eligible:
            print(f"  no wallet has n>={MIN_TRAIN_N} training signals yet "
                  f"(best: {max((s['n'] for s in tr.values()), default=0)}; "
                  f"{len(tr)} wallets observed in training).")
            print("  INSUFFICIENT DATA -- keep collecting.")
            return None

        ranked = sorted(eligible.items(), key=lambda kv: -kv[1]["median"])
        K = TOP_K if len(ranked) >= TOP_K else min(3, len(ranked))
        picked = [w for w, _ in ranked[:K]]
        print(f"  wallets with n>={MIN_TRAIN_N} in training: {len(eligible)}   selecting top {K}")
        print(f"\n  {'#':>2} {'wallet':<46} {'train n':>8} {'train med':>10}")
        print("  " + "-" * 70)
        for i, (w, s) in enumerate(ranked[:K], 1):
            print(f"  {i:>2} {w[:44]:<46} {s['n']:>8} {s['median']:>9.2f}%")

        hv = [r["net"] for r in rs_hold if r["wallet"] in picked]
        hs = stats(hv)
        print("\n  HOLDOUT RESULT (wallets chosen without seeing this data)")
        if not hs:
            print("  no holdout signals for the selected wallets. INSUFFICIENT DATA.")
            return None
        k = sum(1 for x in hv if x > 0)
        p = sign_p(k, hs["n"])
        print(f"  n={hs['n']}  median net {HORIZON}s = {hs['median']:+.2f}%  "
              f"mean {hs['mean']:+.2f}%  %positive {hs['pos']:.1f}%")
        print(f"  sign test (one-sided): {k}/{hs['n']} positive, p = {p:.4f}")

        # separation guard from the preregistration
        all_hold_meds = sorted(s["median"] for s in ho.values() if s["n"] >= 10)
        p75 = all_hold_meds[int(len(all_hold_meds) * 0.75)] if len(all_hold_meds) >= 4 else None
        if p75 is not None:
            print(f"  75th pct of ALL wallets' holdout medians: {p75:+.2f}%   "
                  f"(selected: {hs['median']:+.2f}%)")
        return {"hs": hs, "p": p, "p75": p75,
                "n_eligible": len(eligible), "picked": picked}

    # PRIMARY is Tier B only. Tier A is a frequency-ranked set -- precisely the bias v1
    # identified, and the reason amendment v3.1 built Tier B at all -- so on its own it
    # cannot answer H1. Selecting K from the union would let Tier A (which accumulates
    # usable signals ~3x faster per wallet) fill all five slots and answer the wrong question.
    res_b = analyse(scope_rows(train, "B"), scope_rows(hold, "B"),
                    "PRIMARY: Tier B (unbiased 300-wallet random sample)", True)
    res_u = analyse(train, hold, "SECONDARY: Tier A + Tier B union", False)

    print("\n" + "=" * 90)
    print("VERDICT (from the PRIMARY Tier B analysis only)")
    print("=" * 90)
    if not res_b:
        print("  INCONCLUSIVE -- Tier B has not yet produced a rankable training set.")
        if res_u:
            print(f"  (the union has {res_u['n_eligible']} rankable wallets, but that is "
                  f"not the v3.1 hypothesis and cannot pass it.)")
    else:
        hs, p, p75 = res_b["hs"], res_b["p"], res_b["p75"]
        if hs["n"] < MIN_HOLDOUT_N:
            print(f"  INCONCLUSIVE -- {hs['n']}/{MIN_HOLDOUT_N} holdout signals for the "
                  f"selected wallets. Keep collecting.")
        elif hs["median"] > 0 and p < 0.05 and (p75 is None or hs["median"] > p75):
            print("  H1 PASSES -- selection carries out-of-sample information.")
            print("  Next: v4, on execution at size. Not a licence to trade yet.")
        elif p75 is not None and hs["median"] <= p75:
            print("  KILL -- selected wallets are NOT separated from selection noise")
            print(f"  (holdout median {hs['median']:+.2f}% <= 75th pct {p75:+.2f}%).")
        else:
            print(f"  KILL -- median {hs['median']:+.2f}%, p={p:.4f}.")

    if res_u:
        uh = res_u["hs"]
        print(f"\n  [secondary, NOT the verdict] union A+B: n={uh['n']} "
              f"median {uh['median']:+.2f}% p={res_u['p']:.4f}")

    print("\n  Reminder: do not re-run with a different K or horizon to find a pass.")
    print("  Reminder: Tier B is a 300/4533 (6.6%) sample -- a null bounds that sample only.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
