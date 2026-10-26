"""Order cap = qty × category ceiling (no flat £3000); lip gloss £82×100 → needs_quote."""
from __future__ import annotations

from app.utils.landed_cost import compute_landed_cost
from app.utils.order_sanity import assess_order_total, order_goods_cap_gbp


def test_cap_is_ceiling_times_qty_retail():
    cap = order_goods_cap_gbp("lip gloss bulk", 100, price_type="retail")
    # retail cosmetics ceiling £45 → 4500
    assert abs(cap - 4500.0) < 1.0


def test_lip_gloss_82_x100_needs_quote():
    hit = assess_order_total(
        8200.0,
        query="lip gloss bulk",
        quantity=100,
        price_type="retail",
    )
    assert hit["needs_quote"] is True
    assert hit["hide"] is True
    assert any(g.get("rule") == "goods_over_cap" for g in hit["hard_guards"])

    listing = {
        "title": "Wholesale Lip Gloss Bulk Pack",
        "price": "£82",
        "extracted_price": 82,
        "link": "https://www.ebay.co.uk/itm/1",
        "vendor": "eBay - joy017",
        "price_type": "retail",
        "uk_retail_priced": True,
        "origin_country": "UK",
        "_benchmark_query": "lip gloss bulk",
    }
    landed = compute_landed_cost(
        listing,
        quantity=100,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="UK",
        buyer_vat_registered=False,
    )
    assert landed is not None
    assert landed.get("needs_quote") is True or landed.get("hide_landed") is True
    assert any("goods_over_cap" in str(r) for r in (landed.get("price_flag_reasons") or []))
