"""Does the published v1 result survive the audit's defects?

Recompute the v1 headline under variants that fix each defect the audit found, and see how far
the numbers move. If they barely move, the writeup stands. If they move materially, it needs
another correction.

Variants:
  baseline   : stored net_pct; duplicate (id,h) fills resolved by LAST (what fold() does)
  A first-fill: duplicate fills resolved by FIRST instead
  B recomputed: net = gross - friction(signal), instead of the stored net_pct
  C both
  D minus-oor : drop the 8 pool signals whose friction is outside [0,25]
"""
import collections
import io
import json
import os
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KT = r"C:\killtest-rig"
sys.path.insert(0, KT)
os.chdir(KT)
import kt_verdict as kv          # noqa: E402

V1 = "d3753551dc57aa1b"
sigs_all, _ = kv.fold({"log_dir": "logs"})
sigs, _ = kv.dedup_first_per_wallet_mint(sigs_all)
v1 = [s for s in sigs if str(s.get("config_fp")) == V1]
usable = [s for s in v1 if s.get("entry_price") and s.get("usable")]


def lat(s):
    v = s.get("latency_sec_slot")
    return v if v is not None else s.get("latency_sec")


pool = [s for s in usable if lat(s) is not None and lat(s) <= 60.0]

# all forwards for pool ids, in file order
fwd = collections.defaultdict(list)
with io.open(os.path.join(KT, "logs", "signals.jsonl"), encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == "forward" and r.get("h") == 300:
            fwd[r.get("id")].append(r)


def net_for(s, mode):
    """Resolve the 300s net for a signal under a variant."""
    rs = fwd.get(s.get("id"), [])
    if not rs:
        return None
    r = rs[0] if mode in ("first", "both") else rs[-1]
    if mode in ("recomputed", "both"):
        g = r.get("gross_pct")
        if not isinstance(g, (int, float)):
            return None
        return g - float(s.get("friction_pct") or 0.0)
    n = r.get("net_pct")
    return float(n) if isinstance(n, (int, float)) else None


def report(name, rows):
    vals = [n for _, n in rows]
    if not vals:
        print(f"  {name:<26} (no data)")
        return None
    k = sum(1 for v in vals if v > 0)
    med = st.median(vals)
    print(f"  {name:<26} n={len(vals):<5} median {med:+7.3f}%   %>0 {k/len(vals)*100:5.1f}%   "
          f"p={kv.sign_test_p(k, len(vals)):.4f}")
    return med


print("=" * 88)
print("SENSITIVITY OF THE PUBLISHED v1 RESULT TO THE AUDIT'S DEFECTS")
print("=" * 88)
print(f"  pool n={len(pool)}\n")

base = None
for mode, label in (("last", "baseline (as published)"),
                    ("first", "A: duplicate fills -> first"),
                    ("recomputed", "B: net = gross - friction"),
                    ("both", "C: A + B")):
    rows = [(s.get("id"), net_for(s, mode)) for s in pool]
    rows = [(i, n) for i, n in rows if n is not None]
    m = report(label, rows)
    if base is None:
        base = m
    elif m is not None:
        print(f"      -> shift vs baseline: {m - base:+.3f} pp")

oor = {s.get("id") for s in pool
       if isinstance(s.get("friction_pct"), (int, float))
       and not (0 <= s["friction_pct"] <= 25)}
rows = [(s.get("id"), net_for(s, "last")) for s in pool if s.get("id") not in oor]
rows = [(i, n) for i, n in rows if n is not None]
m = report("D: drop implausible friction", rows)
if m is not None and base is not None:
    print(f"      -> shift vs baseline: {m - base:+.3f} pp")

# how bad is the worst case: drop everything the audit flagged
flagged = oor | {i for i, rs in fwd.items() if len(rs) > 1}
rows = [(s.get("id"), net_for(s, "last")) for s in pool if s.get("id") not in flagged]
rows = [(i, n) for i, n in rows if n is not None]
m = report("E: drop ALL flagged signals", rows)
if m is not None and base is not None:
    print(f"      -> shift vs baseline: {m - base:+.3f} pp")

print("\n  Also: the clairvoyance bound under a recomputed net")
for mode, label in (("last", "baseline"), ("recomputed", "net = gross - friction")):
    exc = []
    for s in pool:
        e = kv.max_excursion_pct(s, {})
        if e is None:
            continue
        exc.append(e - float(s.get("friction_pct") or 0.0))
    print(f"    {label:<26} n={len(exc)} median {st.median(exc):+.2f}%")

print("""
  NOTE: max_excursion_pct() reads the signal's `forward` dict, which fold() populated from the
  file, so the excursion itself is unaffected by the duplicate-fill choice; only the friction
  subtraction (and therefore the NET) is.""")
