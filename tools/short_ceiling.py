"""short_ceiling.py -- the SHORT-HORIZON perfect-exit ceiling, net of measured friction.

Answers HANDOFF item 3 (the open question): what is the maximum excursion inside the first
30 s / 60 s / 300 s (and, for context, 900 s / 3600 s) after detection, net of the rig's own
measured friction, on the signal sets the rig actually has?

Three sources, kept separate on purpose:
  A) logs/signals.jsonl forwards   -- one sample per registered horizon (30/60/300/900/3600),
     all fingerprints. Coarse: "max over horizons <= W" is a LOWER bound on the true peak,
     because only those instants were ever priced. For W=30/60 this is literally the single
     forward return at that horizon -- no extra information over buy-and-hold to 30/60 s.
  B) logs/fastpath.jsonl           -- nominally every 3 s for 120 s after detection. Real
     resolution inside the first 30/60 s, but ~1/5 of signals, ~5 distinct price points per
     path (upstream caching), and a Jupiter-vs-DexScreener basis on the first sample.
  C) logs/fastpath.jsonl, basis-adjusted -- measured from the FIRST OBSERVED sample instead of
     from entry_price. This is what a trader who actually started watching at detection could
     have got; it removes the source basis (first sample sits a median ~-6% from entry_price)
     at the cost of discarding the first ~0-3 s of movement.

Ceiling (per signal) = max gross inside the window - that signal's own friction_pct, where
friction_pct = 2*(dex_fee/side + slippage/side) + gas, i.e. a ROUND TRIP. Subtracting it once
is the whole cost. This is the CLAIRVOYANCE number: it assumes you sell exactly at the peak.
It is a CEILING, never an expectancy.

PART 0 verifies the loader against the real instrument (imports kt_verdict and replays its
fold + filter chain), reproduces the published v1 numbers, and quantifies how much each
duplicate-fill convention moves every horizon.

READ-ONLY: opens rig logs for reading only. Writes no file. Reads no key material.
"""
from __future__ import annotations

import collections
import json
import os
import random
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KT = r"C:\killtest-rig"
LOGS = os.path.join(KT, "logs")
V1 = "d3753551dc57aa1b"
V32 = "63b8561732a5c6bc"
HLIST = (30, 60, 300, 900, 3600)
WINDOWS = (30, 60, 300, 900, 3600)
PUB = {30: (-2.44, 31.1), 60: (-2.56, 32.8), 300: (-2.51, 40.1),
       900: (-4.40, 37.8), 3600: (-11.33, 33.3)}   # KILL_TEST_WRITEUP.md, v1 primary pool
PUB_CLAIR = (10.17, 7.27, 13.89, 70.3)


# --------------------------------------------------------------------------- load
def load_signals(path):
    """(sigs by id last-wins, fwd id->h->[(net,gross,price),...], completes, n_signal_lines)."""
    sigs = {}
    fwd = collections.defaultdict(lambda: collections.defaultdict(list))
    completes = {}
    n_sig_lines = 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            k = r.get("kind")
            if k == "signal":
                n_sig_lines += 1
                sigs[r.get("id")] = r
            elif k == "forward":
                try:
                    h = int(r.get("h"))
                except (TypeError, ValueError):
                    continue
                fwd[r.get("id")][h].append((r.get("net_pct"), r.get("gross_pct"), r.get("price")))
            elif k == "complete":
                completes[r.get("id")] = r
    return sigs, fwd, completes, n_sig_lines


def dedup_pairs(sigs, order):
    """kt_verdict's rule verbatim: first (by detected_at) signal per (wallet, mint)."""
    best = {}
    for sid in order:
        s = sigs[sid]
        k = (s.get("wallet"), s.get("mint"))
        cur = best.get(k)
        if cur is None or (s.get("detected_at") or 0) < (sigs[cur].get("detected_at") or 0):
            best[k] = sid
    return list(best.values())


def lat_slot(s):
    v = s.get("latency_sec_slot")
    return v if v is not None else s.get("latency_sec")


def lat_wall(s):
    v = s.get("latency_sec")
    return v if v is not None else s.get("latency_sec_slot")


def pick(fills, mode):
    """A forward fill under an explicit duplicate convention."""
    if not fills:
        return None
    vals = [float(n) for n, g, p in fills if isinstance(n, (int, float))]
    if not vals:
        return None
    if mode == "first":
        return vals[0]
    if mode == "last":
        return vals[-1]
    return max(vals)


def gross_max(sid, hmax, fwd):
    """Ceiling over recorded horizons <= hmax: BEST gross across duplicate fills ('max'),
    which is the right convention for a ceiling."""
    best = None
    for h, fills in fwd.get(sid, {}).items():
        if h > hmax:
            continue
        for net, g, p in fills:
            if isinstance(g, (int, float)):
                best = float(g) if best is None else max(best, float(g))
    return best


# --------------------------------------------------------------------------- stats
def cluster_ci(vals_by_cluster, iters=4000, seed=20261011):
    keys = list(vals_by_cluster)
    if len(keys) < 5:
        return (None, None)
    rnd = random.Random(seed)
    out = []
    for _ in range(iters):
        pool = []
        for _ in range(len(keys)):
            pool.extend(vals_by_cluster[keys[rnd.randrange(len(keys))]])
        if pool:
            out.append(st.median(pool))
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def q(vals, p):
    v = sorted(vals)
    return v[int(p * (len(v) - 1))]


def summ(vals, clusters=None):
    if not vals:
        return None
    n = len(vals)
    d = {"n": n, "med": st.median(vals), "mean": st.mean(vals),
         "p25": q(vals, .25), "p75": q(vals, .75), "p90": q(vals, .90), "p95": q(vals, .95),
         "max": max(vals), "pos": 100.0 * sum(1 for x in vals if x > 0) / n}
    if clusters:
        d["ci"] = cluster_ci(clusters)
    return d


def fmt(d, ci=True):
    if d is None:
        return "n=0"
    s = (f"n={d['n']:<5} med {d['med']:+7.2f}%  mean {d['mean']:+8.2f}%  "
         f"p25 {d['p25']:+7.2f}%  p75 {d['p75']:+7.2f}%  >0 {d['pos']:5.1f}%")
    if ci and d.get("ci") and d["ci"][0] is not None:
        s += f"  CI[{d['ci'][0]:+6.2f},{d['ci'][1]:+6.2f}]"
    return s


# --------------------------------------------------------------------------- main
def main():
    sigpath = os.path.join(LOGS, "signals.jsonl")
    fppath = os.path.join(LOGS, "fastpath.jsonl")
    sigs, fwd, completes, n_sig_lines = load_signals(sigpath)
    order = list(sigs)

    print("=" * 122)
    print("SHORT-HORIZON PERFECT-EXIT CEILING, net of measured friction   |   "
          "source: C:\\killtest-rig\\logs")
    print("=" * 122)
    print(f"signals.jsonl: {n_sig_lines} signal lines -> {len(sigs)} unique ids "
          f"({n_sig_lines - len(sigs)} re-ingest duplicates; fold keeps the last)")
    for fp, c in collections.Counter(s.get("config_fp") for s in sigs.values()).most_common():
        print(f"   fp {str(fp):<20} {c:>6} signal records")

    # ---- pools -----------------------------------------------------------------
    v1_ded = dedup_pairs(sigs, order)
    v1_pool = [sigs[i] for i in v1_ded
               if sigs[i].get("config_fp") == V1 and sigs[i].get("usable")
               and lat_slot(sigs[i]) is not None and lat_slot(sigs[i]) <= 60.0]
    v32_ded = dedup_pairs(sigs, [i for i in order if sigs[i].get("config_fp") == V32])
    v32_pool = [sigs[i] for i in v32_ded
                if sigs[i].get("usable") and lat_wall(sigs[i]) is not None
                and lat_wall(sigs[i]) <= 900.0]
    all_pool = [sigs[i] for i in v1_ded if sigs[i].get("usable")]
    pools = [("v1 primary  (fp d3753551, slot lat<=60s)", v1_pool),
             ("v3.2        (fp 63b85617, wall lat<=900s)", v32_pool),
             ("ALL usable  (any fp, deduped)", all_pool)]
    print(f"\npools: v1={len(v1_pool)}  v3.2={len(v32_pool)}  all-usable={len(all_pool)}")

    print("\nfriction actually recorded (round trip = 2*(0.30% fee + measured impact/side) + gas):")
    print(f"  {'pool':<44} {'n':>5} {'slip/side med':>13} {'slip/side mean':>14} "
          f"{'friction med':>13} {'friction mean':>13} {'friction p90':>13}")
    for name, pool in pools:
        slips = [float(s.get("slippage_pct_per_side")) for s in pool
                 if isinstance(s.get("slippage_pct_per_side"), (int, float))]
        fr = [float(s.get("friction_pct")) for s in pool
              if isinstance(s.get("friction_pct"), (int, float))]
        if not fr:
            continue
        print(f"  {name:<44} {len(fr):>5} {st.median(slips):>12.2f}% {st.mean(slips):>13.2f}% "
              f"{st.median(fr):>12.2f}% {st.mean(fr):>12.2f}% {q(fr,.9):>12.2f}%")
        print(f"  {'':<44} {'':>5} outliers: friction >20% on {sum(1 for x in fr if x>20)}/"
              f"{len(fr)}, >100% on {sum(1 for x in fr if x>100)}/{len(fr)} "
              f"(these wreck the MEAN only; see PART 1b)")

    # ---- PART 0: verification against the real instrument -----------------------
    print("\n" + "=" * 122)
    print("PART 0 -- VERIFICATION. Replays kt_verdict's own fold() + filter chain and compares "
          "with the published v1 numbers.")
    print("=" * 122)
    sys.path.insert(0, KT)
    try:
        import kt_verdict as kv
        kv.config_fingerprint = lambda cfg: V1          # see v1_sweep_recheck.py
        sigs_kv, completes_kv = kv.fold({"log_dir": "logs"})
        ded_kv, dropped = kv.dedup_first_per_wallet_mint(sigs_kv)
        off = [s for s in ded_kv if s.get("config_fp") != V1]
        pool_kv = [s for s in ded_kv if s.get("config_fp") == V1 and s.get("usable")]

        def _lat(s):
            v = s.get("latency_sec_slot")
            return v if v is not None else s.get("latency_sec")
        pool_kv = [s for s in pool_kv if _lat(s) is not None and _lat(s) <= 60.0]

        print(f"  kt_verdict.fold: {len(sigs_kv)} signal ids, dedup dropped {dropped}, "
              f"other-fp excluded {len(off)}, primary pool n={len(pool_kv)}   [published n=357]")
        print(f"\n  {'horizon':>8} {'published':>11} {'fold-replay':>12} {'delta':>8}   "
              f"{'pub %>0':>8} {'replay %>0':>11}")
        for h in HLIST:
            vals = []
            for s in pool_kv:
                f = (s.get("forward") or {}).get(str(h))
                if f and isinstance(f.get("net_pct"), (int, float)):
                    vals.append(float(f["net_pct"]))
            if not vals:
                continue
            pmed, ppos = PUB[h]
            pos = 100 * sum(1 for x in vals if x > 0) / len(vals)
            print(f"  {h:>8} {pmed:>10.2f}% {st.median(vals):>11.2f}% "
                  f"{st.median(vals)-pmed:>+7.2f}pp {ppos:>7.1f}% {pos:>10.1f}%  n={len(vals)}")
        exc = []
        for s in pool_kv:
            e = kv.max_excursion_pct(s, completes_kv)
            if e is not None:
                exc.append(e - float(s.get("friction_pct") or 0.0))
        if exc:
            print(f"\n  clairvoyance, all recorded horizons incl. complete.max_price:")
            print(f"    fold-replay n={len(exc)} median {st.median(exc):+.2f}%  "
                  f">0 {100*sum(1 for x in exc if x>0)/len(exc):.1f}%   "
                  f"[published n=357, {PUB_CLAIR[0]:+.2f}%, CI "
                  f"[{PUB_CLAIR[1]:+.2f},{PUB_CLAIR[2]:+.2f}], {PUB_CLAIR[3]:.1f}%]")
    except Exception as e:
        print(f"  !! kt_verdict replay failed: {type(e).__name__}: {e}")

    print("\n  duplicate-fill convention sensitivity on MY reader (v1 primary pool, n=357):")
    print(f"  {'horizon':>8} {'first-in':>10} {'last-write':>11} {'max-fill':>10}   "
          f"spread   [published]")
    for h in HLIST:
        row = {}
        for mode in ("first", "last", "max"):
            vals = [pick(fwd.get(s["id"], {}).get(h), mode) for s in v1_pool]
            vals = [v for v in vals if v is not None]
            row[mode] = (st.median(vals), len(vals))
        print(f"  {h:>8} {row['first'][0]:>9.2f}% {row['last'][0]:>10.2f}% "
              f"{row['max'][0]:>9.2f}%   {row['max'][0]-row['first'][0]:>+5.2f}pp  "
              f"[{PUB[h][0]:+.2f}%, n={row['first'][1]}]")

    # ---- PART 1: horizon-sampled ceiling ---------------------------------------
    print("\n" + "=" * 122)
    print("PART 1 -- HORIZON-SAMPLED CEILING (signals.jsonl). For W=30/60 there is exactly one")
    print("sample inside the window, so the 'ceiling' IS buy-and-hold to W. W=300+ adds samples.")
    print("=" * 122)
    for name, pool in pools:
        print(f"\n{name}")
        for W in WINDOWS:
            ceil, hold = [], []
            cl, clh = collections.defaultdict(list), collections.defaultdict(list)
            for s in pool:
                sid, fr = s["id"], float(s.get("friction_pct") or 0.0)
                g = gross_max(sid, W, fwd)
                if g is None:
                    continue
                hs = [h for h in fwd.get(sid, {}) if h <= W]
                hmax = max(hs)
                hn = pick(fwd[sid].get(hmax), "last")
                v = float(g) - fr
                ceil.append(v)
                cl[s.get("mint")].append(v)
                if hn is not None:
                    hold.append(hn)
                    clh[s.get("mint")].append(hn)
            if not ceil:
                continue
            dc = summ(ceil, cl)
            dh = summ(hold, clh) if hold else None
            print(f"  W={W:>4}s  NET ceiling: {fmt(dc)}")
            if dh:
                print(f"            buy&hold-to-W med {dh['med']:+7.2f}%  mean {dh['mean']:+8.2f}%  "
                      f"| ceiling - hold = {dc['med']-dh['med']:+.2f}pp median   "
                      f"| worst-5% mean {st.mean(sorted(ceil)[:max(1,len(ceil)//20)]):+.1f}%")

    # ---- PART 1b: friction-outlier sensitivity ---------------------------------
    print("\n" + "=" * 122)
    print("PART 1b -- FRICTION-OUTLIER SENSITIVITY. The audit found out-of-range friction_pct")
    print("(up to 9,800%). They are genuine measured impact on an illiquid pool, but they must be")
    print("shown not to be carrying the conclusion. Medians with and without friction > 20%:")
    print("=" * 122)
    for name, pool in pools:
        print(f"\n{name}")
        for W in WINDOWS:
            allv, clean = [], []
            for s in pool:
                g = gross_max(s["id"], W, fwd)
                if g is None:
                    continue
                fr = float(s.get("friction_pct") or 0.0)
                v = float(g) - fr
                allv.append(v)
                if fr <= 20.0:
                    clean.append(v)
            if not clean:
                continue
            print(f"  W={W:>4}s  all n={len(allv):<5} med {st.median(allv):+6.2f}%   "
                  f"friction<=20% n={len(clean):<5} med {st.median(clean):+6.2f}%   "
                  f"delta {st.median(clean)-st.median(allv):+.2f}pp   "
                  f"(excluded {len(allv)-len(clean)})")

    # ---- PART 2: fastpath ceiling ----------------------------------------------
    print("\n" + "=" * 122)
    print("PART 2 -- FASTPATH CEILING (first 120 s, nominal 3 s ticks). "
          "vs entry = rig convention; basis-adj = measured from first observed sample.")
    print("=" * 122)
    paths = collections.defaultdict(list)
    n_fp_lines = 0
    with open(fppath, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("t_sec") is None or o.get("ret_pct") is None:
                continue
            n_fp_lines += 1
            paths[o.get("id")].append((float(o["t_sec"]), float(o["ret_pct"])))
    print(f"fastpath.jsonl: {n_fp_lines} samples over {len(paths)} signal ids; "
          f"joined to signals: {sum(1 for i in paths if i in sigs)}/{len(paths)}")
    tot = collections.Counter(s.get("config_fp") for s in sigs.values())
    for fp, c in collections.Counter(sigs[i].get("config_fp") for i in paths if i in sigs).most_common():
        print(f"   fp {str(fp):<20} fastpath {c:>5} / {tot.get(fp,0):>6} "
              f"({100*c/max(1,tot.get(fp,0)):4.1f}% of that fingerprint's signals)")

    def fp_rows(selector, min_samples=8):
        out, seen = [], set()
        for sid, pts in paths.items():
            s = sigs.get(sid)
            if not s or not s.get("usable") or not selector(s) or len(pts) < min_samples:
                continue
            k = (s.get("wallet"), s.get("mint"))
            if k in seen:
                continue
            seen.add(k)
            out.append((sid, s, sorted(pts)))
        return out

    fp_sets = [("v1 primary fastpath subset", fp_rows(
        lambda s: s.get("config_fp") == V1 and lat_slot(s) is not None and lat_slot(s) <= 60.0)),
        ("all usable fastpath signals", fp_rows(lambda s: True))]

    for name, rows in fp_sets:
        if not rows:
            continue
        print(f"\n{name}: n={len(rows)} paths")
        dist = []
        for _, _, pts in rows:
            uniq = []
            for t, r in pts:
                if not uniq or uniq[-1][1] != r:
                    uniq.append((t, r))
            dist.append(len(uniq))
        gaps = [pts[i+1][0]-pts[i][0] for _, _, pts in rows for i in range(len(pts)-1)]
        basis = [pts[0][1] for _, _, pts in rows]
        print(f"  samples/path med {st.median(len(p) for _,_,p in rows):.0f}   "
              f"distinct price points/path med {st.median(dist):.0f}   "
              f"median gap {st.median(gaps):.2f}s   "
              f"| first-sample basis: med {st.median(basis):+.2f}%  "
              f"mean {st.mean(basis):+.2f}%  p10 {q(basis,.1):+.1f}%  p90 {q(basis,.9):+.1f}%")
        for W in (3, 30, 60, 120):
            raw, adj, hold = [], [], []
            clr, cla = collections.defaultdict(list), collections.defaultdict(list)
            beats = 0
            for _, s, pts in rows:
                sub = [(t, r) for t, r in pts if t <= W]
                if not sub:
                    continue
                fr = float(s.get("friction_pct") or 0.0)
                b = pts[0][1]
                rmax = max(r for _, r in sub)
                raw.append(rmax - fr)
                adj.append(rmax - b - fr)
                clr[s.get("mint")].append(rmax - fr)
                cla[s.get("mint")].append(rmax - b - fr)
                hold.append(sub[-1][1] - b - fr)
                if any(r > b + 0.5 for _, r in sub[1:]):
                    beats += 1
            dr, da, dhold = summ(raw, clr), summ(adj, cla), summ(hold)
            print(f"  W={W:>3}s  vs entry:      {fmt(dr)}")
            print(f"           basis-adj:     {fmt(da)}")
            print(f"           hold(adj) med {dhold['med']:+7.2f}% p75 {dhold['p75']:+7.2f}% "
                  f"p90 {dhold['p90']:+7.2f}%  | adj ceiling p75 {da['p75']:+7.2f}% "
                  f"p90 {da['p90']:+7.2f}% p95 {da['p95']:+7.2f}% max {da['max']:+.0f}%"
                  f"  | a later sample beats the first by >0.5pp in {100*beats/len(rows):.0f}% of paths")

        # representativeness: does the fastpath subset look like the rest of the pool?
        ids = {sid for sid, _, _ in rows}
        # NOTE: `(lat_slot(s) or 1e9)` was a self-inflicted bug here -- a legitimate 0.0 s
        # latency is falsy, so it dropped exactly the fastest (same-slot) signals. Explicit
        # None check, same as PART 1.
        for label, key in (("v1 primary", lambda s: s.get("config_fp") == V1
                            and lat_slot(s) is not None and lat_slot(s) <= 60.0),
                           ("all usable", lambda s: True)):
            base = [s for s in sigs.values() if s.get("usable") and key(s)]
            base = [sigs[i] for i in dedup_pairs(sigs, [s["id"] for s in base])]
            inx = [pick(fwd.get(s["id"], {}).get(30), "last") for s in base if s["id"] in ids]
            outx = [pick(fwd.get(s["id"], {}).get(30), "last") for s in base if s["id"] not in ids]
            inx = [x for x in inx if x is not None]
            outx = [x for x in outx if x is not None]
            if inx and outx:
                print(f"  representativeness, {label}: net@30s median  sampled-by-fastpath "
                      f"{st.median(inx):+.2f}% (n={len(inx)})  vs not-sampled {st.median(outx):+.2f}% "
                      f"(n={len(outx)})  -> {st.median(inx)-st.median(outx):+.2f}pp")

    # ---- PART 3: does the short ceiling clear friction? -------------------------
    print("\n" + "=" * 122)
    print("PART 3 -- DOES THE SHORT-WINDOW CEILING CLEAR FRICTION BY A WIDE MARGIN?  "
          "(per-signal: max excursion in window - that signal's own friction)")
    print("=" * 122)
    for name, rows in fp_sets:
        if not rows:
            continue
        print(f"\n  {name}")
        for W in (30, 60, 120):
            nets, gross, fr = [], [], []
            for _, s, pts in rows:
                sub = [(t, r) for t, r in pts if t <= W]
                if not sub:
                    continue
                b = pts[0][1]
                g = max(r for _, r in sub) - b
                f = float(s.get("friction_pct") or 0.0)
                gross.append(g)
                fr.append(f)
                nets.append(g - f)
            if not nets:
                continue
            print(f"    W={W:>3}s  gross ceiling: med {st.median(gross):+6.2f}%  "
                  f"mean {st.mean(gross):+7.2f}%  | friction: med {st.median(fr):.2f}%  "
                  f"mean {st.mean(fr):.2f}%  | NET ceiling med {st.median(nets):+6.2f}%  "
                  f"mean {st.mean(nets):+7.2f}%  "
                  f"| clears friction in {100*sum(1 for x in nets if x>0)/len(nets):4.1f}% of signals")
            for F in (2.78, 4.60):
                s2 = [g - F for g in gross]
                print(f"            at a flat {F:.2f}% round-trip friction: "
                      f"med {st.median(s2):+6.2f}%  mean {st.mean(s2):+7.2f}%  "
                      f"clears in {100*sum(1 for x in s2 if x>0)/len(s2):4.1f}%")
    print("\n  A ceiling must clear friction by a WIDE margin to be a premise: no causal rule")
    print("  collects the peak, and the rig's own no-information control showed entry timing")
    print("  after detection carries no measurable information (median paired difference 0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
