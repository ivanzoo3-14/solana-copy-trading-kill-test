"""qa.invariants -- the data-quality invariants as pure, importable, testable functions.

Each invariant takes plain dicts (a signal or forward record as read from the JSONL logs) and
returns a list of human-readable violation strings. An empty list means the record passes.

Deliberately dependency-free (no numpy/pandas), no I/O, no network, no hardcoded paths, so the
same functions run in CI against synthetic fixtures and against the real logs locally.

The most valuable checks are the INTERNAL ARITHMETIC ones: net == gross - friction, and
gross == (price/entry - 1)*100. Nothing else verifies those, and if they fail every number
derived from them is wrong. These are the ones the grant's M2 milestone exists for.
"""
from __future__ import annotations

from typing import Dict, List, Optional

REQUIRED_SIGNAL_FIELDS = ("id", "wallet", "mint", "detected_at", "config_fp", "usable",
                          "friction_pct", "latency_sec", "latency_sec_slot")
KNOWN_FINGERPRINTS = {"d3753551dc57aa1b", "6a9f1ff9c87aeea0", "2a7f0cfbbce45424",
                      "224d6bdb82639f44", "63b8561732a5c6bc"}
HORIZONS = {30, 60, 300, 900, 3600, 14400, 86400}
ALLOWED_TIERS = {"A", "B", None}
ALLOWED_SLOT_SOURCES = {"batch", "caller", "per_signal", None}


def signal_field_problems(s: Dict) -> List[str]:
    """Required fields present on every signal record."""
    return [f"missing required field {k!r}" for k in REQUIRED_SIGNAL_FIELDS if k not in s]


def signal_arithmetic_problems(s: Dict) -> List[str]:
    """Numeric sanity: values that are the wrong type or sign."""
    out: List[str] = []
    if not isinstance(s.get("detected_at"), (int, float)):
        out.append("detected_at is not numeric")
    if isinstance(s.get("latency_sec"), (int, float)) and s["latency_sec"] < 0:
        out.append(f"latency_sec is negative ({s['latency_sec']})")
    if isinstance(s.get("latency_sec_slot"), (int, float)) and s["latency_sec_slot"] < 0:
        out.append("latency_sec_slot is negative")
    ep = s.get("entry_price")
    if ep is not None and not (isinstance(ep, (int, float)) and ep > 0):
        out.append("entry_price present but not > 0")
    fp = s.get("friction_pct")
    if isinstance(fp, (int, float)) and not (0 <= fp <= 25):
        out.append(f"friction_pct out of [0,25]: {fp}")
    return out


def signal_consistency_problems(s: Dict) -> List[str]:
    """Cross-field consistency and vocabulary checks."""
    out: List[str] = []
    if s.get("usable"):
        if not s.get("entry_price"):
            out.append("usable signal has no entry_price")
        if s.get("unusable_reason"):
            out.append("usable signal carries an unusable_reason")
    else:
        if not s.get("unusable_reason"):
            out.append("non-usable signal has no unusable_reason")
    if str(s.get("config_fp")) not in KNOWN_FINGERPRINTS:
        out.append(f"unknown config_fp {s.get('config_fp')!r}")
    if s.get("tier") not in ALLOWED_TIERS:
        out.append(f"invalid tier {s.get('tier')!r}")
    if s.get("detect_slot_source") not in ALLOWED_SLOT_SOURCES:
        out.append(f"invalid detect_slot_source {s.get('detect_slot_source')!r}")
    if (isinstance(s.get("slot"), (int, float))
            and isinstance(s.get("detect_slot"), (int, float))
            and s["detect_slot"] < s["slot"]):
        out.append("detect_slot < slot (slot-boundary violation)")
    for key in ("wallet", "mint"):
        v = str(s.get(key) or "")
        if not (32 <= len(v) <= 44):
            out.append(f"{key} does not look like a base58 pubkey (len {len(v)})")
    return out


def forward_reference_problems(fwd: Dict, signals: Dict[str, Dict]) -> List[str]:
    """A forward record must point at a real signal, a configured horizon, and a positive price."""
    out: List[str] = []
    if fwd.get("id") not in signals:
        out.append(f"forward references unknown signal id {fwd.get('id')!r}")
    if fwd.get("h") not in HORIZONS:
        out.append(f"unknown horizon {fwd.get('h')!r}")
    if not isinstance(fwd.get("price"), (int, float)) or not (fwd["price"] > 0):
        out.append("price is not > 0")
    return out


def forward_arithmetic_problems(fwd: Dict, sig: Optional[Dict]) -> List[str]:
    """The checks that matter most: net == gross - friction, gross == (price/entry - 1)*100,
    and age_sec >= horizon."""
    out: List[str] = []
    if sig is None or not isinstance(fwd.get("net_pct"), (int, float)) \
            or not isinstance(fwd.get("gross_pct"), (int, float)):
        return out
    fric = float(sig.get("friction_pct") or 0.0)
    if abs((fwd["gross_pct"] - fric) - fwd["net_pct"]) > 0.01:
        out.append(f"net != gross - friction: gross={fwd['gross_pct']} fric={fric} "
                   f"net={fwd['net_pct']}")
    if sig.get("entry_price") and isinstance(fwd.get("price"), (int, float)):
        g = (fwd["price"] / sig["entry_price"] - 1.0) * 100.0
        if abs(g - fwd["gross_pct"]) > 0.05:
            out.append(f"gross != (price/entry-1)*100: computed={g:.3f} stored={fwd['gross_pct']}")
    if isinstance(fwd.get("age_sec"), (int, float)) and fwd.get("h") and fwd["age_sec"] < fwd["h"] - 1:
        out.append(f"age_sec {fwd['age_sec']} < horizon {fwd['h']}")
    return out


def fastpath_arithmetic_problems(rec: Dict) -> List[str]:
    """Fastpath: ret_pct == (price/entry - 1)*100, and price > 0."""
    out: List[str] = []
    e, p, ret = rec.get("entry"), rec.get("price"), rec.get("ret_pct")
    if not isinstance(p, (int, float)) or not (p > 0):
        out.append("fastpath price not > 0")
    if e and isinstance(p, (int, float)) and isinstance(ret, (int, float)):
        g = (p / e - 1.0) * 100.0
        if abs(g - ret) > 0.05:
            out.append(f"ret != (price/entry-1)*100: computed={g:.3f} stored={ret}")
    return out
