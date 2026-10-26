"""INR/₹ parse + INR→PKR conversion (live FX preferred; static fallback labeled)."""
from __future__ import annotations

import re

from app.core.region_profile import load_profile
from app.utils.fx import convert_amount, fetch_usd_rate
from app.utils.money import parse_money


def _detect_listing_currency(raw: str) -> str:
    if re.search(r"₹|\bINR\b", raw, re.I):
        return "INR"
    if re.search(r"Rs\.?|\bPKR\b", raw, re.I):
        return "PKR"
    return "USD"


def test_parse_rupee_symbol_90_per_piece():
    assert parse_money("₹ 90/piece") == 90.0
    assert parse_money("₹90") == 90.0


def test_parse_rupee_1200_per_kg():
    assert parse_money("₹ 1,200 per kg") == 1200.0


def test_rs_vs_rupee_symbol_ambiguity():
    """Plain 'Rs' is treated as PKR; '₹' is INR — same digits, different currency."""
    assert _detect_listing_currency("Rs. 1,200 Soft Hand Towel Pack") == "PKR"
    assert _detect_listing_currency("₹ 1,200 Soft Hand Towel Pack") == "INR"
    assert parse_money("Rs. 1,200") == 1200.0
    assert parse_money("₹ 1,200") == 1200.0


def test_inr_to_pkr_conversion_meta():
    pk = load_profile("pk")
    pkr_fb = float(pk["fx_to_usd_fallback"])
    inr_fb = 1 / 83

    amt_inr = parse_money("₹ 90/piece")
    assert amt_inr == 90.0
    converted, meta = convert_amount(
        amt_inr,
        "INR",
        "PKR",
        from_fallback=inr_fb,
        to_fallback=pkr_fb,
    )
    assert converted is not None and converted > 0
    assert "from" in meta and "to" in meta
    assert meta["from"].get("source") in (
        "frankfurter.app",
        "open.er-api.com",
        "static_fallback",
    )
    assert meta["to"].get("source") in (
        "frankfurter.app",
        "open.er-api.com",
        "static_fallback",
    )
    assert "as_of" in meta["from"] and "as_of" in meta["to"]
    if meta.get("used_fallback"):
        # Static path: 90 * (278/83) ≈ 301.45
        expected = 90.0 * (278.0 / 83.0)
        assert abs(converted - expected) < 1.0
        assert meta["from"]["source"] == "static_fallback" or meta["to"]["source"] == "static_fallback"

    # Unit column style used by market-service formatLocalApprox for PKR
    unit_col = f"≈ Rs {round(converted):,}"
    assert unit_col.startswith("≈ Rs")


def test_fetch_usd_rate_labels_fallback():
    hit = fetch_usd_rate("INR", fallback_to_usd=1 / 83)
    assert hit.get("rate_to_usd")
    assert hit.get("source") in (
        "frankfurter.app",
        "open.er-api.com",
        "static_fallback",
    )
    assert "as_of" in hit
    assert isinstance(hit.get("used_fallback"), bool)
