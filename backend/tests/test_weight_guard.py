"""Weight plausibility guard: reject carton-like page weights; warn at 3× landed/goods."""
from __future__ import annotations

from unittest.mock import patch

from app.utils.landed_cost import compute_landed_cost, resolve_unit_weight_kg


def _phone_case(**extra):
    row = {
        "title": "Alcantara Phone Case for iPhone",
        "price": "$9.00",
        "link": "https://www.alibaba.com/product-detail/phone-case_1.html",
        "supplier_origin": "CN",
        "currency": "USD",
        "price_source": "page",
        "is_product_page": True,
    }
    row.update(extra)
    return row


def test_eight_kg_phone_case_page_weight_rejected():
    listing = _phone_case(
        package_weight_kg=8.0,
        package_weight_raw="Package Weight: 8 kg",
        package_weight_source="page",
        package_weight_basis="unknown",
        package_weight_kg_as_parsed=8.0,
    )
    resolved = resolve_unit_weight_kg(listing, foreign=True)
    assert resolved["ignored"] is True
    assert "carton/gross" in (resolved.get("ignore_reason") or "").lower()
    assert resolved["kg"] == 0.05  # category assumed for phone case
    assert resolved["from_page"] is False

    with patch("app.utils.landed_cost._shipping_band") as ship:
        ship.return_value = (
            {"low": 10.0, "mid": 10.0, "high": 10.0},
            {
                "method": "weight_x_freight",
                "freight_assumption": "fixture",
                "total_kg": 5.0,
                "weight_kg_unit": 0.05,
                "weight_from_page": False,
            },
        )
        landed = compute_landed_cost(
            listing,
            quantity=100,
            local_currency="GBP",
            location="London, United Kingdom",
            country_code="uk",
            origin_country="CN",
        )
    assert landed is not None
    assert landed["weight_ignored"] is True
    assert landed["package_weight_kg"] == 0.05
    assert landed["weight_from_page"] is False
    assert "page weight ignored" in (landed.get("weight_ignore_reason") or "").lower()
    how = landed.get("weight_how") or ""
    assert "8" in how
    assert "assumed" in how.lower() or "0.05" in how


def test_carton_weight_with_pcs_converted():
    listing = _phone_case(
        package_weight_kg=0.08,  # 8 kg / 100 pcs
        package_weight_raw="Gross weight: 8 kg",
        package_weight_source="page",
        package_weight_basis="carton",
        package_weight_pcs_per_carton=100,
        package_weight_kg_as_parsed=8.0,
        package_weight_note="carton/gross 8 kg ÷ 100 pcs/carton → 0.08 kg/unit",
    )
    resolved = resolve_unit_weight_kg(listing, foreign=True)
    assert resolved["ignored"] is False
    assert abs(float(resolved["kg"]) - 0.08) < 1e-9
    assert resolved["from_page"] is True
    assert resolved["pcs_per_carton"] == 100
    assert "÷" in (resolved.get("how") or "") or "100" in (resolved.get("how") or "")


def test_landed_goods_multiple_warning_above_3x():
    listing = _phone_case(
        package_weight_kg=0.05,
        package_weight_source="assumed",
    )

    def _heavy_ship(**_kwargs):
        return (
            {"low": 5000.0, "mid": 5000.0, "high": 5000.0},
            {
                "method": "weight_x_freight",
                "freight_assumption": "heavy fixture",
                "total_kg": 800.0,
                "weight_kg_unit": 8.0,
                "weight_from_page": True,
            },
        )

    with patch("app.utils.landed_cost._shipping_band", side_effect=_heavy_ship):
        landed = compute_landed_cost(
            listing,
            quantity=100,
            local_currency="GBP",
            location="London, UK",
            country_code="uk",
            origin_country="CN",
        )
    assert landed is not None
    assert landed["freight_dominates_warning"] is True
    assert float(landed["landed_goods_multiple"] or 0) > 3.0
    blob = "\n".join(landed.get("assumptions") or [])
    assert ">3" in blob or "3×" in blob or "3x" in blob.lower()
    # Tier visibility
    assert landed.get("price_tier_unit")
    assert landed.get("price_card_raw") == "$9.00"
    assert "Price tier used" in blob


def test_brief_tier_reason_and_profile_minimum_freight():
    listing = _phone_case(
        unit_usd=11.0,
        moq=12,
        package_weight_source="assumed",
    )
    landed = compute_landed_cost(
        listing,
        quantity=100,
        local_currency="GBP",
        location="London, UK",
        country_code="uk",
        origin_country="CN",
    )
    assert landed is not None
    assert (
        landed["price_tier_explanation"]
        == "used $11 (tier for this quantity unverified; page shows $9.00)"
    )
    assert landed["minimum_freight_applied"] is True
    assert landed["shipping_amount"] == "£45"
    minimum = landed["minimum_freight"]
    assert minimum["effective_date"]
    assert minimum["source_url"]
    blob = "\n".join(landed.get("assumptions") or [])
    assert "estimated, not a carrier quote" in blob
    assert "Price tier used: used $11" in blob
