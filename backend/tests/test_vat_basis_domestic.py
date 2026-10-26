"""Domestic VAT basis: includes/excludes VAT × registered/unregistered."""
from __future__ import annotations

from app.utils.landed_cost import compute_landed_cost
from app.utils.vat_basis import apply_domestic_vat_basis, infer_price_includes_vat


def _row(price: str, *, price_type: str = "retail", link: str = "https://www.argos.co.uk/product/1"):
    return {
        "title": "Test product",
        "price": price,
        "extracted_price": price.replace("£", "").replace("GBP", "").strip(),
        "link": link,
        "vendor": "Argos",
        "price_type": price_type,
        "uk_retail_priced": price_type == "retail",
        "origin_country": "UK",
        "is_local": True,
        "_benchmark_query": "test product",
    }


def test_infer_retail_includes_vat():
    assert infer_price_includes_vat({"price_type": "retail"}) is True
    assert infer_price_includes_vat({"price_type": "trade"}) is False
    assert infer_price_includes_vat({"price_type": "unknown"}) is None


def test_apply_includes_unregistered_as_shown():
    r = apply_domestic_vat_basis(
        7.2, vat_rate=0.2, buyer_vat_registered=False, price_includes_vat=True
    )
    assert abs(r["goods_for_mid"] - 7.2) < 1e-6
    assert r["domestic_vat_in_mid"] is False


def test_apply_includes_registered_div_1_2():
    r = apply_domestic_vat_basis(
        7.2, vat_rate=0.2, buyer_vat_registered=True, price_includes_vat=True
    )
    assert abs(r["goods_for_mid"] - 6.0) < 1e-6
    assert r["domestic_vat_reclaimable"] is True


def test_ubuy_072_x10():
    # Unit already normalised to £0.72 (post pack÷50); avoid re-splitting pack in title
    listing = {
        **_row("£0.72", link="https://www.u-buy.co.uk/product/x"),
        "title": "Nisbets Essentials Foil Containers unit price",
        "vendor": "u-buy.co.uk",
        "price_type": "retail",
        "uk_retail_priced": True,
        "uk_origin_class": "confirmed_UK",
        "pack_units": None,
        "price_may_be_per_pack": False,
    }
    for vat_reg, expect in ((False, 7.2), (True, 6.0)):
        landed = compute_landed_cost(
            listing,
            quantity=10,
            local_currency="GBP",
            location="London, United Kingdom",
            country_code="uk",
            origin_country="UK",
            buyer_vat_registered=vat_reg,
        )
        assert landed is not None
        assert landed["vat_basis"] == "includes_vat"
        assert landed["price_includes_vat"] is True
        assert abs(float(landed["estimated_total_amount"]) - expect) < 0.05, (
            vat_reg,
            landed.get("estimated_total"),
            landed.get("estimated_total_amount"),
        )


def test_argos_25_x100():
    listing = _row("£25.00")
    listing["title"] = "Argos Home Ceramic Mug"
    listing["vendor"] = "Argos"
    for vat_reg, expect in ((False, 2500.0), (True, 2500.0 / 1.2)):
        landed = compute_landed_cost(
            listing,
            quantity=100,
            local_currency="GBP",
            location="London, United Kingdom",
            country_code="uk",
            origin_country="UK",
            buyer_vat_registered=vat_reg,
        )
        assert landed is not None
        assert landed["vat_basis"] == "includes_vat"
        assert abs(float(landed["estimated_total_amount"]) - expect) < 0.5


def test_amazon_19_x100():
    listing = _row(
        "£19.00",
        link="https://www.amazon.co.uk/dp/B00TESTAKE",
    )
    listing["title"] = "Nylon Dog Lead"
    listing["vendor"] = "Amazon.co.uk"
    for vat_reg, expect in ((False, 1900.0), (True, 1900.0 / 1.2)):
        landed = compute_landed_cost(
            listing,
            quantity=100,
            local_currency="GBP",
            location="London, United Kingdom",
            country_code="uk",
            origin_country="UK",
            buyer_vat_registered=vat_reg,
        )
        assert landed is not None
        assert landed["vat_basis"] == "includes_vat"
        assert abs(float(landed["estimated_total_amount"]) - expect) < 0.5


def test_trade_excludes_vat_adds_20_when_unregistered():
    listing = {
        "title": "Catering foil roll trade pack",
        "price": "£10.00",
        "extracted_price": "10",
        "link": "https://www.nisbets.co.uk/product/foil",
        "vendor": "Nisbets",
        "price_type": "trade",
        "origin_country": "UK",
        "is_local": True,
        "_benchmark_query": "catering foil rolls",
    }
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
    assert landed.get("is_import") is False
    assert landed["vat_basis"] == "excludes_vat"
    # 100 + 20% = 120
    assert abs(float(landed["estimated_total_amount"]) - 120.0) < 0.5


def test_trade_excludes_vat_registered_net():
    listing = {
        "title": "Catering foil roll trade pack",
        "price": "£10.00",
        "extracted_price": "10",
        "link": "https://www.nisbets.co.uk/product/foil",
        "vendor": "Nisbets",
        "price_type": "trade",
        "origin_country": "UK",
        "is_local": True,
        "_benchmark_query": "catering foil rolls",
    }
    landed = compute_landed_cost(
        listing,
        quantity=10,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="UK",
        buyer_vat_registered=True,
    )
    assert landed is not None
    assert landed.get("is_import") is False
    assert abs(float(landed["estimated_total_amount"]) - 100.0) < 0.5
    assert landed["domestic_vat_reclaimable"] is True
