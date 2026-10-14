"""DATA QUALITY AUDIT -- every invariant we can state, checked against the real logs.

Runs on numpy/pandas only (already installed). NO network, NO installs, NO writes, and it does
not touch the live venv the rig is running from.

The most valuable checks are the INTERNAL ARITHMETIC ones -- net == gross - friction, and
gross == (price/entry - 1)*100. Nothing has ever verified those, and if they fail, every
published number derived from them is wrong.
"""
import collections
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KT = r"C:\killtest-rig"
LOGS = os.path.join(KT, "logs")
KNOWN_FP = {"d3753551dc57aa1b", "6a9f1ff9c87aeea0", "2a7f0cfbbce45424",
            "224d6bdb82639f44", "63b8561732a5c6bc"}
HORIZONS = {30, 60, 300, 900, 3600, 14400, 86400}

findings = []


def check(name, bad, total, detail="", severity="FAIL"):
    pct = (bad / total * 100) if total else 0.0
    tag = "ok  " if bad == 0 else severity
    print(f"  [{tag}] {name:<52} {bad:>6}/{total:<8} {pct:>6.2f}%  {detail}")
    if bad:
        findings.append((name, bad, total, detail))


print("=" * 100)
print("DATA QUALITY AUDIT -- signals.jsonl")
print("=" * 100)

sig = {}
fwd = []
dupe_sig_ids = 0
with io.open(os.path.join(LOGS, "signals.jsonl"), encoding="utf-8", errors="replace") as f:
    for ln, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            findings.append(("unparseable line", 1, 1, f"line {ln}"))
            continue
        if r.get("kind") == "signal":
            if r.get("id") in sig:
                dupe_sig_ids += 1
            sig[r.get("id")] = r
        elif r.get("kind") == "forward":
            fwd.append(r)

nsig = len(sig)
nfwd = len(fwd)
print(f"  records: {nsig} signals, {nfwd} forwards\n")

# ---- signal-level invariants
check("signal id unique", dupe_sig_ids, nsig)

req = ["id", "wallet", "mint", "detected_at", "config_fp", "usable", "friction_pct",
       "latency_sec", "latency_sec_slot", "forward"]
for k in req:
    check(f"signal.{k} present", sum(1 for s in sig.values() if k not in s), nsig)

check("detected_at is numeric",
      sum(1 for s in sig.values()
          if not isinstance(s.get("detected_at"), (int, float))), nsig)

neg_wall = sum(1 for s in sig.values()
               if isinstance(s.get("latency_sec"), (int, float)) and s["latency_sec"] < 0)
check("latency_sec >= 0", neg_wall, nsig, "(negative = clock offset / same-slot)"
      if neg_wall else "")

neg_slot = sum(1 for s in sig.values()
               if isinstance(s.get("latency_sec_slot"), (int, float))
               and s["latency_sec_slot"] < 0)
check("latency_sec_slot >= 0", neg_slot, nsig)

bad_entry = sum(1 for s in sig.values()
                if s.get("entry_price") is not None and not (s["entry_price"] > 0))
check("entry_price > 0 when present", bad_entry, nsig)

# usable implies an entry price
u_rows = [s for s in sig.values() if s.get("usable")]
check("usable => entry_price present",
      sum(1 for s in u_rows if not s.get("entry_price")), len(u_rows))

check("usable => no unusable_reason",
      sum(1 for s in u_rows if s.get("unusable_reason")), len(u_rows))
nu_rows = [s for s in sig.values() if not s.get("usable")]
check("not usable => unusable_reason present",
      sum(1 for s in nu_rows if not s.get("unusable_reason")), len(nu_rows))

bad_fric = sum(1 for s in sig.values()
               if isinstance(s.get("friction_pct"), (int, float))
               and not (0 <= s["friction_pct"] <= 25))
check("friction_pct in [0,25]", bad_fric, nsig)

bad_fp = sum(1 for s in sig.values() if str(s.get("config_fp")) not in KNOWN_FP)
check("config_fp is a known fingerprint", bad_fp, nsig)

bad_tier = sum(1 for s in sig.values() if s.get("tier") not in ("A", "B", None))
check("tier in {A,B,None}", bad_tier, nsig)

SRC_OK = {"batch", "caller", "per_signal", None}
check("detect_slot_source in allowed set",
      sum(1 for s in sig.values() if s.get("detect_slot_source") not in SRC_OK), nsig)

check("slot <= detect_slot",
      sum(1 for s in sig.values()
          if isinstance(s.get("slot"), (int, float))
          and isinstance(s.get("detect_slot"), (int, float))
          and s["detect_slot"] < s["slot"]), nsig)

bad_len = sum(1 for s in sig.values()
              if not (32 <= len(str(s.get("wallet") or "")) <= 44)
              or not (32 <= len(str(s.get("mint") or "")) <= 44))
check("wallet/mint look like base58 pubkeys", bad_len, nsig)

# ---- forward-level invariants (the arithmetic nobody has checked)
print()
check("forward.id references an existing signal",
      sum(1 for r in fwd if r.get("id") not in sig), nfwd)

check("forward.h in configured horizons",
      sum(1 for r in fwd if r.get("h") not in HORIZONS), nfwd)

pair_seen = collections.Counter((r.get("id"), r.get("h")) for r in fwd)
dupes = sum(c - 1 for c in pair_seen.values() if c > 1)
check("(id, horizon) unique -- no duplicate fills", dupes, nfwd)

bad_price = sum(1 for r in fwd if not isinstance(r.get("price"), (int, float))
                or not (r["price"] > 0))
check("forward.price > 0", bad_price, nfwd)

# ARITHMETIC 1: net == gross - friction
arith1 = 0
arith1_ex = []
for r in fwd:
    s = sig.get(r.get("id"))
    if not s or not isinstance(r.get("net_pct"), (int, float)):
        continue
    fric = float(s.get("friction_pct") or 0.0)
    if abs((r["gross_pct"] - fric) - r["net_pct"]) > 0.01:
        arith1 += 1
        if len(arith1_ex) < 2:
            arith1_ex.append((r.get("id"), r.get("h"), r["gross_pct"], fric, r["net_pct"]))
check("ARITHMETIC net == gross - friction", arith1, nfwd,
      f"e.g. {arith1_ex[0]}" if arith1_ex else "")

# ARITHMETIC 2: gross == (price/entry - 1)*100
arith2 = 0
arith2_ex = []
for r in fwd:
    s = sig.get(r.get("id"))
    if not s or not s.get("entry_price") or not isinstance(r.get("price"), (int, float)):
        continue
    if not isinstance(r.get("gross_pct"), (int, float)):
        continue
    g = (r["price"] / s["entry_price"] - 1.0) * 100.0
    if abs(g - r["gross_pct"]) > 0.05:
        arith2 += 1
        if len(arith2_ex) < 2:
            arith2_ex.append((r.get("id"), r.get("h"), round(g, 3), r["gross_pct"]))
check("ARITHMETIC gross == (price/entry-1)*100", arith2, nfwd,
      f"e.g. {arith2_ex[0]}" if arith2_ex else "")

# ARITHMETIC 3: age_sec >= horizon
bad_age = sum(1 for r in fwd
              if isinstance(r.get("age_sec"), (int, float)) and r.get("h")
              and r["age_sec"] < r["h"] - 1)
check("forward.age_sec >= its horizon", bad_age, nfwd)

# ---- fastpath
print("\n" + "=" * 100)
print("DATA QUALITY AUDIT -- fastpath.jsonl")
print("=" * 100)
fp_path = os.path.join(LOGS, "fastpath.jsonl")
pathed = collections.defaultdict(list)
nrec = 0
bad_parse = 0
with io.open(fp_path, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        nrec += 1
        try:
            o = json.loads(line)
        except ValueError:
            bad_parse += 1
            continue
        pathed[o.get("id")].append(o)
print(f"  records: {nrec}   distinct signal ids: {len(pathed)}\n")
check("fastpath records parse", bad_parse, nrec)

dup_ts = 0
nonmono = 0
over120 = 0
arith3 = 0
bad_price_fp = 0
for sid, recs in pathed.items():
    ts = [r.get("t_sec") for r in recs if r.get("t_sec") is not None]
    if len(ts) != len(set(ts)):
        dup_ts += 1
    if ts != sorted(ts):
        nonmono += 1
    if any(t > 120.5 for t in ts):
        over120 += 1
    for r in recs:
        if not isinstance(r.get("price"), (int, float)) or not (r["price"] > 0):
            bad_price_fp += 1
        e, p, ret = r.get("entry"), r.get("price"), r.get("ret_pct")
        if e and isinstance(p, (int, float)) and isinstance(ret, (int, float)):
            g = (p / e - 1.0) * 100.0
            if abs(g - ret) > 0.05:
                arith3 += 1
npaths = len(pathed)
check("(id, t_sec) unique", dup_ts, npaths)
check("t_sec monotonic per id", nonmono, npaths)
check("t_sec <= 120", over120, npaths)
check("fastpath.price > 0", bad_price_fp, nrec)
check("ARITHMETIC ret == (price/entry-1)*100", arith3, nrec)

# coverage
for fp in ("d3753551dc57aa1b", "63b8561732a5c6bc"):
    ids = {s.get("id") for s in sig.values() if str(s.get("config_fp")) == fp}
    cov = len(ids & set(pathed))
    print(f"  [info] fastpath coverage for {fp}: {cov}/{len(ids)} "
          f"({cov/max(1,len(ids))*100:.1f}%)")

print("\n" + "=" * 100)
print("SUMMARY")
print("=" * 100)
if not findings:
    print("  every invariant held.")
else:
    print(f"  {len(findings)} check(s) found problems:")
    for name, bad, total, detail in findings:
        print(f"    - {name}: {bad}/{total}  {detail}")
