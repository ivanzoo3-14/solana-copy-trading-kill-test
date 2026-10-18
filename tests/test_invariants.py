"""Tests for qa.invariants.

Each invariant is checked against a clean record (must pass) and a corrupted record (must be
caught). Runs with no data, no network, no keys -- so it runs in CI in seconds.

The three arithmetic invariants are the point of the whole suite: if net != gross - friction,
or gross != (price/entry - 1)*100, every published number derived from them is wrong.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qa.invariants import (  # noqa: E402
    fastpath_arithmetic_problems,
    forward_arithmetic_problems,
    forward_reference_problems,
    signal_arithmetic_problems,
    signal_consistency_problems,
    signal_field_problems,
)

FP = "63b8561732a5c6bc"  # a known fingerprint


def good_signal():
    return {"id": "sig1", "wallet": "A" * 32, "mint": "B" * 32, "detected_at": 100.0,
            "config_fp": FP, "usable": True, "friction_pct": 1.5,
            "latency_sec": 0.0, "latency_sec_slot": 0.0, "entry_price": 1.0,
            "tier": "B", "detect_slot_source": "per_signal", "slot": 200, "detect_slot": 201}


def good_forward(sig):
    return {"id": sig["id"], "h": 60, "price": 1.10, "gross_pct": 10.0, "net_pct": 8.5,
            "age_sec": 60.0}


def test_clean_signal_passes_everything():
    s = good_signal()
    assert signal_field_problems(s) == []
    assert signal_arithmetic_problems(s) == []
    assert signal_consistency_problems(s) == []


def test_missing_required_field_is_caught():
    s = good_signal()
    del s["friction_pct"]
    assert any("friction_pct" in p for p in signal_field_problems(s))


def test_negative_latency_is_caught():
    s = good_signal()
    s["latency_sec"] = -5.0
    assert signal_arithmetic_problems(s)


def test_nonpositive_entry_is_caught():
    s = good_signal()
    s["entry_price"] = 0.0
    assert signal_arithmetic_problems(s)


def test_usable_without_entry_is_caught():
    s = good_signal()
    s["entry_price"] = None
    assert signal_consistency_problems(s)


def test_unknown_fingerprint_is_caught():
    s = good_signal()
    s["config_fp"] = "deadbeef"
    assert signal_consistency_problems(s)


def test_arithmetic_net_equals_gross_minus_friction():
    s = good_signal()
    assert forward_arithmetic_problems(good_forward(s), s) == []  # 10.0 - 1.5 = 8.5 = net
    f2 = good_forward(s)
    f2["net_pct"] = 7.0  # wrong: should be 8.5
    assert forward_arithmetic_problems(f2, s)


def test_arithmetic_gross_equals_price_over_entry():
    s = good_signal()
    assert not any("gross" in p for p in forward_arithmetic_problems(good_forward(s), s))
    f2 = good_forward(s)
    f2["gross_pct"] = 5.0  # wrong: price 1.10 / entry 1.0 -> +10.0
    assert any("gross" in p for p in forward_arithmetic_problems(f2, s))


def test_forward_references_unknown_signal():
    f = good_forward(good_signal())
    f["id"] = "nope"
    assert forward_reference_problems(f, {})


def test_forward_horizon_must_be_configured():
    f = good_forward(good_signal())
    f["h"] = 999
    assert any("horizon" in p for p in forward_reference_problems(f, {"sig1": good_signal()}))


def test_fastpath_ret_equals_price_over_entry():
    assert fastpath_arithmetic_problems({"entry": 1.0, "price": 1.05, "ret_pct": 5.0}) == []
    assert fastpath_arithmetic_problems({"entry": 1.0, "price": 1.05, "ret_pct": 1.0})


def test_fastpath_price_must_be_positive():
    assert fastpath_arithmetic_problems({"price": -1.0})
