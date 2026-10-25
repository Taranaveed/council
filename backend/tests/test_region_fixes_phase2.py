"""Regression suite for region / landed-cost / Skip / prompt fixes."""
from __future__ import annotations

import re

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
    assert ca["sales_tax_rate"] == 0.2  # UK import VAT
    landed = compute_landed_cost(
        listing,
        quantity=50,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="EU",
        buyer_vat_registered=False,
    )
    assert landed is not None
    assert landed["is_import"] is True
    assert landed["duty_rate"] == 0.12
    assert landed["sales_tax_rate"] == 0.2
    assert landed["domestic_vat_rate"] in (0, 0.0)
    assert float(landed["estimated_total_amount"]) > 0


def test_uk_us_origin_treated_as_import():
    uk = load_profile("uk")
    assert import_origin_group(uk, "US") == "import"
    listing = _uk_listing(
        "US",
        link="https://www.amazon.com/dp/B00TEST",
        price="$12.00",
    )
    ca = shared_cost_assumptions(
        profile=uk, listing=listing, local_currency="GBP", origin_country="US"
    )
    assert ca["is_import"] is True
    assert ca["duty_rate_mid"] == 0.12
    assert ca["sales_tax_rate"] == 0.2
    landed = compute_landed_cost(
        listing,
        quantity=100,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="US",
        buyer_vat_registered=False,
    )
    assert landed is not None
    assert landed["is_import"] is True
    assert landed["origin_country"] in ("US", "USA", "UNITED STATES") or landed[
        "origin_country"
    ] == "US"
    assert landed["duty_rate"] == 0.12
    assert landed["duty_fallback"] is True
    assert landed["sales_tax_rate"] == 0.2
    assert landed["domestic_vat_in_mid"] is False
    assert float(landed["estimated_total_amount"]) > float(
        _parse_goods_approx(landed)
    )


def _parse_goods_approx(landed: dict) -> float:
    """Goods line ≈ mid before duty/freight/VAT — use line_total parse."""
    import re

    m = re.search(r"([\d,]+(?:\.\d+)?)", str(landed.get("line_total") or ""))
    return float(m.group(1).replace(",", "")) if m else 0.0


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


def test_limited_data_landed_shown_under_no_match():
    """One priced kept row still gets a landed mid, labeled limited data; verdict stays NO_MATCH."""
    from app.utils.relevance import no_good_matches_verdict
    from app.utils.supplier_table import attach_limited_data_landed

    listing = _uk_listing(
        "CN",
        link="https://www.alibaba.com/product-detail/limited-1.html",
        price="$9.00",
    )
    attached = attach_limited_data_landed(
        [listing],
        quantity=100,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
    )
    assert len(attached) == 1
    landed = attached[0]["landed_cost"]
    assert landed is not None
    assert landed.get("limited_data") is True
    assert "limited data" in str(landed.get("limited_data_label") or "").lower()
    mid = landed_mid_display(attached[0])
    assert mid != "needs quote"
    assert "limited data" in mid.lower()
    assert "low confidence" in mid.lower()

    verdict = no_good_matches_verdict("phone case", dropped=5)
    assert verdict["verdict"] == "NO_MATCH"
    table = build_supplier_table(
        attached,
        verdict=verdict,
        quantity=100,
        is_bulk=True,
    )
    assert table[0]["best_pick"] is False
    assert table[0]["landed_mid"] == mid
    assert table[0]["landed_cost"]["limited_data"] is True


def test_uk_prompts_contain_no_pakistan_karachi_cra():
    uk_ctx = {
        "trade_zone": "UK",
        "currency": "GBP",
        "region_profile_id": "uk",
        "regulatory_focus": load_profile("uk").get("regulatory_focus") or "",
    }
    blobs = [
        marketplace_addon(None, None, uk_ctx, buying_mode="bulk", quantity=100),
        thrift_advocate_prompt(location_context=uk_ctx, buying_mode="bulk", quantity=100),
        risk_analyst_prompt(location_context=uk_ctx, buying_mode="bulk", quantity=100),
        deal_judge_prompt(location_context=uk_ctx, buying_mode="bulk", quantity=100),
    ]
    banned = (
        "Pakistan",
        "Karachi",
        "Lahore",
        "Consumer Rights Act",
        "Rs 1",
    )
    for blob in blobs:
        for word in banned:
            assert word not in blob, f"Found {word!r} in prompt"
        assert not re.search(r"\bRs\.?\b", blob), "Found Rs token in UK prompt"
        assert not re.search(r"\bPKR\b", blob), "Found PKR in UK prompt"
        # Trade Assurance may appear only as a forbidden-unless-sourced example
        for m in re.finditer(r"Trade Assurance", blob):
            window = blob[max(0, m.start() - 80) : m.end() + 40]
            assert "Do NOT name" in window or "SOURCED-FACTS" in blob[max(0, m.start() - 400) : m.start()], (
                f"Trade Assurance outside sourced-facts forbid list: {window!r}"
            )


def test_bulk_addon_fx_example_is_currency_neutral():
    from app.agents.deal_finder_prompts import bulk_buying_addon

    text = bulk_buying_addon(buying_mode="bulk", quantity=100)
    assert "Rs 1" not in text
    assert not re.search(r"\bRs\.?\b", text)
    assert "1:1 local currency" in text or "never treat a USD amount as 1:1" in text


def test_sourced_facts_rule_bans_unsourced_trade_assurance():
    uk_ctx = {
        "trade_zone": "UK",
        "currency": "GBP",
        "region_profile_id": "uk",
        "regulatory_focus": load_profile("uk").get("regulatory_focus") or "",
    }
    blob = marketplace_addon(None, None, uk_ctx, buying_mode="bulk", quantity=100)
    assert "SOURCED-FACTS RULE" in blob
    assert "Trade Assurance" in blob  # named as forbidden-unless-sourced example
    assert "Money Back Guarantee" in blob
    # The rule must forbid inventing those brands without a listing/profile fact
    assert "unless that exact" in blob.lower() or "unless that exact phrase" in blob


def test_scrub_unsourced_trade_assurance_when_not_in_listings():
    from app.utils.sourced_facts import scrub_unsourced_coverage_brands, scrub_agent_texts

    prose = (
        "Pay only via Alibaba Trade Assurance or a credit-card that permits chargebacks."
    )
    cleaned = scrub_unsourced_coverage_brands(prose, sourced_blob="phone case Alibaba CN")
    assert "Trade Assurance" not in cleaned
    assert "on-platform payment" in cleaned.lower() or "chargeback" in cleaned.lower()

    # Keep when listing facts mention it
    kept = scrub_unsourced_coverage_brands(
        prose, sourced_blob="Seller offers Trade Assurance on this order"
    )
    assert "Trade Assurance" in kept

    scrubbed = scrub_agent_texts(
        {"thrift_advocate": prose, "risk_analyst": "ok"},
        listings=[{"title": "Case", "snippet": "MOQ 100"}],
    )
    assert "Trade Assurance" not in scrubbed["thrift_advocate"]
    assert scrubbed["risk_analyst"] == "ok"


def test_uk_cif_duty_base_includes_freight():
    """
    CIF duty: duty_base = goods + freight.
    goods 1100, freight 118, duty 12% → duty 146.16, VAT 272.83, landed 1636.99.
    """
    from unittest.mock import patch

    listing = {
        "title": "CIF fixture phone case",
        "price": "£11.00",
        "link": "https://www.alibaba.com/product-detail/cif-fixture.html",
        "supplier_origin": "CN",
        "currency": "GBP",
        "price_source": "page",
        "is_product_page": True,
        "package_weight_kg": 0.118,  # 100 × 0.118 = 11.8 kg; overridden via ship band mock
        "package_weight_source": "page",
    }

    def _fake_ship(**kwargs):
        return (
            {"low": 118.0, "mid": 118.0, "high": 118.0},
            {
                "method": "weight_x_freight",
                "freight_assumption": "fixture freight 118",
                "total_kg": 11.8,
                "weight_kg_unit": 0.118,
                "weight_from_page": True,
            },
        )

    with patch("app.utils.landed_cost._shipping_band", side_effect=_fake_ship):
        # Force unit currency GBP so goods = 11 × 100 = 1100 with no FX
        with patch(
            "app.utils.landed_cost._detect_currency",
            return_value="GBP",
        ):
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
    assert abs(float(landed["goods_amount"]) - 1100.0) < 0.02
    assert abs(float(landed["duty_base_amount"]) - 1218.0) < 0.02  # 1100+118
    assert abs(float(landed["duty_amount_value"]) - 146.16) < 0.02
    assert abs(float(landed["vat_base_amount"]) - 1364.16) < 0.02
    # VAT 20% of 1364.16 = 272.832
    assert abs(float(landed["estimated_total_amount"]) - 1636.99) < 0.02
    assert "duty base" in (landed.get("formula") or "").lower() or "CIF duty base" in (
        landed.get("formula") or ""
    )
    assert "Freight derivation:" in "\n".join(landed.get("assumptions") or [])


def test_serp_dollar_price_under_uk_request_is_usd_not_gbp():
    """SERP '$11' (or factory £ rewrite) under a UK/GBP request must FX-convert, not same_currency."""
    listing = {
        "title": "Alcantara Phone Case",
        "price": "$11.00",
        "link": "https://www.alibaba.com/product-detail/phone-case_123.html",
        "supplier_origin": "CN",
        "currency": "GBP",  # wrongly annotated as buyer currency
        "price_source": "serp",
        "is_product_page": True,
        "package_weight_kg": 0.15,
        "package_weight_source": "assumed",
    }
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
    assert landed["unit_price_parsed_currency"] == "USD"
    assert landed["unit_price_raw"] == "$11.00"
    fx = landed.get("fx_meta") or {}
    assert fx.get("source") != "same_currency"
    # Goods in GBP must be FX'd (~11 / ~1.27 ≈ 8.66), not 1100
    assert float(landed["goods_amount"]) < 1000.0

    # Factory host with £ display (buyer-locale scrape bug) still treated as USD
    rewritten = dict(listing)
    rewritten["price"] = "£11.00"
    landed2 = compute_landed_cost(
        rewritten,
        quantity=100,
        local_currency="GBP",
        location="London, UK",
        country_code="uk",
        origin_country="CN",
    )
    assert landed2 is not None
    assert landed2["unit_price_parsed_currency"] == "USD"
    assert (landed2.get("fx_meta") or {}).get("source") != "same_currency"
