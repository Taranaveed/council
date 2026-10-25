"""Regression suite for region / landed-cost / Skip / prompt fixes."""
from __future__ import annotations

import pytest

from app.agents.deal_finder_prompts import (
    deal_judge_prompt,
    marketplace_addon,
    risk_analyst_prompt,
    thrift_advocate_prompt,
)
from app.core.region_profile import (
    RegionNotSupportedError,
    get_profile,
    import_origin_group,
    load_profile,
)
from app.utils.cost_assumptions import shared_cost_assumptions
from app.utils.landed_cost import compute_landed_cost
from app.utils.supplier_table import build_supplier_table, landed_mid_display
from app.utils.verdict_verify import clear_best_pick


def _uk_listing(origin: str, *, link: str, price: str = "£10.00") -> dict:
    return {
        "title": f"Sample {origin}",
        "price": price,
        "link": link,
        "supplier_origin": origin,
        "price_source": "page",
        "is_product_page": True,
        "package_weight_kg": 0.2,
        "package_weight_source": "page",
    }


def test_unsupported_us_not_supported():
    with pytest.raises(RegionNotSupportedError) as ei:
        get_profile(location="New York, United States", currency="USD")
    assert ei.value.profile_id == "us"
    assert "not supported" in ei.value.detail.lower()


def test_uk_uk_origin_duty_zero_domestic_vat_line():
    uk = load_profile("uk")
    listing = _uk_listing("UK", link="https://www.argos.co.uk/product/1", price="£20.00")
    ca = shared_cost_assumptions(
        profile=uk,
        listing=listing,
        local_currency="GBP",
        origin_country="UK",
        buyer_vat_registered=False,
    )
    assert ca["is_import"] is False
    assert ca["duty_rate_mid"] == 0.0
    assert ca["sales_tax_rate"] == 0.0  # import VAT
    assert ca["domestic_vat_rate"] == 0.2
    assert ca["domestic_vat_in_mid"] is True

    landed = compute_landed_cost(
        listing,
        quantity=10,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="UK",
        buyer_vat_registered=False,
    )
    assert landed is not None
    assert landed["duty_rate"] == 0.0
    assert landed["is_import"] is False
    assert landed["domestic_vat_rate"] == 0.2
    assert landed["domestic_vat_in_mid"] is True
    # 10 × 20 = 200 + 20% VAT = 240
    assert abs(float(landed["estimated_total_amount"]) - 240.0) < 0.02


def test_uk_uk_origin_vat_reclaimable_when_registered():
    listing = _uk_listing("UK", link="https://www.johnlewis.com/x", price="£20.00")
    landed = compute_landed_cost(
        listing,
        quantity=10,
        local_currency="GBP",
        location="London, UK",
        country_code="uk",
        origin_country="UK",
        buyer_vat_registered=True,
    )
    assert landed is not None
    assert landed["duty_rate"] == 0.0
    assert landed["domestic_vat_reclaimable"] is True
    assert landed["domestic_vat_in_mid"] is False
    # mid excludes reclaimable domestic VAT → 200
    assert abs(float(landed["estimated_total_amount"]) - 200.0) < 0.02
    assert float(landed["domestic_vat_amount"]) == 40.0


def test_uk_cn_origin_is_import_with_fallback_duty():
    listing = _uk_listing(
        "CN",
        link="https://www.alibaba.com/product-detail/x.html",
        price="$5.00",
    )
    landed = compute_landed_cost(
        listing,
        quantity=100,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="CN",
        buyer_vat_registered=False,
    )
    assert landed is not None
    assert landed["is_import"] is True
    assert landed["duty_rate"] == 0.12
    assert landed["duty_fallback"] is True
    assert landed["duty_fallback_label"] == "estimated, not a tariff lookup"
    assert "estimated, not a tariff lookup" in (landed.get("duty_assumption") or "")


def test_uk_eu_origin_treated_as_import():
    uk = load_profile("uk")
    assert import_origin_group(uk, "EU") == "import"
    listing = _uk_listing("EU", link="https://www.europages.co.uk/x", price="€8.00")
    ca = shared_cost_assumptions(
        profile=uk, listing=listing, local_currency="GBP", origin_country="EU"
    )
    assert ca["is_import"] is True
    assert ca["duty_rate_mid"] == 0.12


def test_table_brief_agents_same_landed_mid():
    listing = _uk_listing("CN", link="https://www.alibaba.com/product-detail/y.html", price="$2.00")
    landed = compute_landed_cost(
        listing,
        quantity=50,
        local_currency="GBP",
        location="Manchester, UK",
        country_code="uk",
        origin_country="CN",
    )
    assert landed is not None
    listing["landed_cost"] = landed
    listing["best_pick"] = True
    table = build_supplier_table(
        [listing],
        verdict={"verdict": "BUY", "winner": {"link": listing["link"]}, "landed_cost": landed},
        quantity=50,
    )
    assert table[0]["landed_mid"] == landed_mid_display(listing)
    assert table[0]["landed_mid"] == landed["estimated_total"] or table[0][
        "landed_mid"
    ].startswith(str(landed["estimated_total"]))
    # Agent-facing mid is the same estimated_total string
    assert landed["estimated_total"] in table[0]["landed_mid"]


def test_skip_clears_best_keeps_landed():
    listing = _uk_listing("UK", link="https://www.argos.co.uk/product/2", price="£15")
    landed = compute_landed_cost(
        listing,
        quantity=5,
        local_currency="GBP",
        location="London, UK",
        country_code="uk",
        origin_country="UK",
    )
    listing["landed_cost"] = landed
    listing["best_pick"] = True
    cleared = clear_best_pick([listing])
    assert cleared[0]["best_pick"] is False
    assert cleared[0]["landed_cost"] is landed

    table = build_supplier_table(
        cleared,
        verdict={
            "verdict": "SKIP",
            "winner": {"link": "", "title": "", "vendor": ""},
        },
        quantity=5,
    )
    assert table[0]["best_pick"] is False
    assert table[0]["landed_mid"] != "needs quote"
    assert table[0]["landed_cost"] is not None


def test_needs_quote_when_no_landed():
    row = {"title": "x", "price": "£1", "link": "https://example.com"}
    assert landed_mid_display(row) == "needs quote"
    table = build_supplier_table([row], verdict={"verdict": "SKIP"}, quantity=1)
    assert table[0]["landed_mid"] == "needs quote"


def test_uk_prompts_contain_no_pakistan_karachi_cra():
    uk_ctx = {
        "trade_zone": "UK",
        "currency": "GBP",
        "region_profile_id": "uk",
        "regulatory_focus": load_profile("uk").get("regulatory_focus") or "",
    }
    blobs = [
        marketplace_addon(None, None, uk_ctx),
        thrift_advocate_prompt(location_context=uk_ctx),
        risk_analyst_prompt(location_context=uk_ctx),
        deal_judge_prompt(location_context=uk_ctx),
    ]
    banned = ("Pakistan", "Karachi", "Consumer Rights Act")
    for blob in blobs:
        for word in banned:
            assert word not in blob, f"Found {word!r} in prompt"
