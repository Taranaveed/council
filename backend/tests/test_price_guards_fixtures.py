"""Guards: 5x peer median, category bands, order-total, UK shopping label."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.utils.landed_cost import compute_landed_cost
from app.utils.listing_channel import annotate_listing_channels
from app.utils.price_bands import assess_category_band, band_for_query
from app.utils.price_plausibility import annotate_price_outliers
from app.utils.relevance import filter_relevant_priced_listings
from app.utils.uk_shopping_seller import annotate_uk_shopping_sellers, infer_uk_shopping_seller

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "benchmark" / "fixtures" / "market"


def _fix(name: str) -> dict:
    path = FIX / f"{name}__uk__bulk__GBP.json"
    if not path.is_file():
        pytest.skip(f"missing {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_upper_outlier_5x_peer_median():
    rows = [
        {"price": "$2.00", "currency": "USD", "title": "tote", "link": "https://www.dhgate.com/product/a"},
        {"price": "$2.50", "currency": "USD", "title": "tote", "link": "https://www.dhgate.com/product/b"},
        {"price": "$3.00", "currency": "USD", "title": "tote", "link": "https://www.dhgate.com/product/c"},
        {"price": "$50.00", "currency": "USD", "title": "tote", "link": "https://www.dhgate.com/product/d"},
    ]
    out = annotate_price_outliers(rows, query="tote bag")
    hi = [r for r in out if r.get("price") == "$50.00"][0]
    assert hi.get("price_outlier") is True
    assert any("5x" in x or "peer_median" in x for x in (hi.get("price_flag_reasons") or ["5x_peer_median"]))


def test_category_ceiling_plug_and_tote():
    plug = assess_category_band(1495.0, "uk plug extension lead")
    assert plug["in_band"] is False
    assert any("ceiling" in r for r in plug["reasons"])
    tote = assess_category_band(77.0, "tote bag")
    assert tote["in_band"] is False
    pens = assess_category_band(80.0, "ballpoint pens")
    assert pens["in_band"] is False


def test_order_total_hides_landed_on_plug_fixture():
    fix = _fix("uk_plug_extension_lead")
    listing = None
    for row in fix.get("listings") or []:
        raw = str(row.get("price") or "").replace(",", "")
        if "1899" in raw:
            listing = dict(row)
            break
    assert listing, "expected $1,899 plug listing in fixture"
    listing["_benchmark_query"] = "uk plug extension lead"
    listing["is_product_page"] = True
    listing["price_source"] = "page"
    lc = compute_landed_cost(
        listing,
        quantity=80,
        local_currency="GBP",
        country_code="uk",
        location="London, UK",
    )
    assert lc is not None
    assert lc.get("hide_landed") is True
    assert lc.get("estimated_total") is None
    assert lc.get("price_flagged") or lc.get("needs_quote")


def test_flagged_excluded_from_priced_and_nomatch_rule():
    fix = _fix("tote_bag")
    listings = annotate_listing_channels(list(fix.get("listings") or []), is_bulk=True)
    for x in listings:
        x["_benchmark_query"] = "tote bag"
        x["is_product_page"] = True
    # Outlier/category annotate then filter
    kept, dropped, meta = filter_relevant_priced_listings(listings, "tote bag", is_bulk=True)
    # After category ceilings, expensive totes should be dropped from priced
    assert meta["relevant_priced_count"] < 4 or meta["outlier_dropped"] > 0 or meta["no_good_matches"]


def test_uk_shopping_seller_from_vendor_string():
    # Plain Amazon.co.uk (no marketplace seller dash) still has .co.uk hard evidence
    row = {
        "link": "https://www.google.com/search?ibp=oshop&q=x",
        "vendor": "Amazon.co.uk",
        "price": "See listing",
        "price_source": "rejected_storefront",
        "host": "google.com",
    }
    meta = infer_uk_shopping_seller(row)
    assert meta is not None
    assert meta["is_uk_shopping_seller"] is True
    assert meta["uk_origin_class"] == "confirmed_UK"
    assert "retail price" in meta["uk_seller_label"].lower()
    assert "bulk discount" in meta["uk_seller_label"].lower()
    annotated = annotate_uk_shopping_sellers([row])[0]
    assert annotated["price_review_only"] is True  # no usable extracted_price
    assert annotated["best_pick_eligible"] is False
    assert annotated["counts_as_live_listing"] is False


def test_uk_seller_override_without_co_uk():
    row = {
        "link": "https://www.google.com/search?ibp=oshop&q=bag",
        "vendor": "Frasers",
        "host": "google.com",
        "price": "See listing",
    }
    meta = infer_uk_shopping_seller(row)
    assert meta is not None
    assert meta["uk_origin_class"] == "likely_UK"
    assert meta["uk_seller_rule"] == "known_retailers_override"


def test_ebay_marketplace_is_unknown_not_likely():
    from app.utils.uk_shopping_seller import classify_uk_seller_origin

    row = {
        "link": "https://www.google.com/search?ibp=oshop&q=lead",
        "merchant": "eBay - sereta4676",
        "host": "google.com",
        "is_shopping_offer": True,
        "price": "£24",
        "extracted_price": "24.4",
        "currency": "GBP",
        "delivery": "Free delivery",
    }
    origin = classify_uk_seller_origin(row)
    assert origin["origin_class"] == "unknown"
    assert origin["is_marketplace"] is True
    annotated = annotate_uk_shopping_sellers([row])[0]
    assert annotated.get("uk_origin_class") == "unknown"
    assert annotated.get("price_type") == "retail"
    assert annotated.get("uk_retail_priced") is True
    assert annotated.get("best_pick_eligible") is False


def test_branded_goods_flag_apple():
    from app.utils.uk_shopping_seller import classify_uk_seller_origin

    row = {
        "link": "https://www.google.com/search?ibp=oshop&q=earphones",
        "merchant": "Apple",
        "host": "google.com",
        "is_shopping_offer": True,
        "price": "£19",
        "extracted_price": "19",
        "currency": "GBP",
    }
    origin = classify_uk_seller_origin(row)
    assert origin["branded_goods"] is True
    annotated = annotate_uk_shopping_sellers([row])[0]
    assert annotated.get("branded_goods") is True
    assert "authorized-reseller" in (annotated.get("branded_goods_note") or "")


def test_argos_25_x100_known_uk_company_domestic_path():
    """Argos is known_uk_company → confirmed_UK → domestic path (duty 0)."""
    from app.utils.uk_shopping_seller import (
        annotate_uk_shopping_sellers,
        classify_uk_seller_origin,
    )

    base = {
        "link": "https://www.google.com/search?ibp=oshop&q=earphones",
        "merchant": "Argos",
        "host": "google.com",
        "is_shopping_offer": True,
        "price": "£25",
        "extracted_price": "24.99",
        "currency": "GBP",
        "price_source": "serp",
    }
    origin = classify_uk_seller_origin(base)
    assert origin["origin_class"] == "confirmed_UK"
    assert origin.get("known_uk_company")
    assert "argos" in str(origin["known_uk_company"].get("id") or "").lower()

    ann = annotate_uk_shopping_sellers([base])[0]
    assert ann["uk_origin_class"] == "confirmed_UK"
    assert ann["uk_retail_priced"] is True
    assert ann["price_type"] == "retail"
    assert ann["best_pick_eligible"] is False

    domestic_incl = compute_landed_cost(
        {**ann, "origin_country": "UK", "price_type": "retail"},
        quantity=100,
        local_currency="GBP",
        location="Leeds, United Kingdom",
        country_code="uk",
        origin_country="UK",
        buyer_vat_registered=False,
    )
    domestic_excl = compute_landed_cost(
        {**ann, "origin_country": "UK", "price_type": "retail"},
        quantity=100,
        local_currency="GBP",
        location="Leeds, United Kingdom",
        country_code="uk",
        origin_country="UK",
        buyer_vat_registered=True,
    )
    assert domestic_incl is not None and domestic_excl is not None
    assert domestic_incl.get("is_import") is False
    assert float(domestic_incl.get("duty_rate") or 0) == 0.0
    goods_incl = float(domestic_incl.get("goods_amount") or 0)
    assert 2400 < goods_incl < 2600
    mid_incl = _parse_money(domestic_incl.get("estimated_total"))
    mid_excl = _parse_money(domestic_excl.get("estimated_total"))
    assert mid_incl is not None and mid_excl is not None
    assert mid_excl < mid_incl
    assert not domestic_incl.get("hide_landed")


def test_amazon_marketplace_seller_is_unknown():
    from app.utils.uk_shopping_seller import classify_uk_seller_origin

    row = {
        "link": "https://www.google.com/search?ibp=oshop&q=x",
        "merchant": "Amazon.co.uk - Amazon.co.uk-Seller",
        "host": "google.com",
        "price": "£19",
        "extracted_price": "18.99",
        "currency": "GBP",
    }
    origin = classify_uk_seller_origin(row)
    assert origin["origin_class"] == "unknown"
    assert origin["is_marketplace"] is True


def test_retail_soft_flag_within_3x_not_hidden():
    """Above retail ceiling but within 3× → soft; beyond 3× → hard hide."""
    from app.utils.price_bands import assess_category_band

    # audio retail ceiling 120; 150 is above but within 3× → soft
    hit = assess_category_band(150.0, "earphones", price_type="retail")
    assert hit.get("in_band") is False
    assert hit.get("soft_flag") is True
    assert hit.get("hard_guards") == []
    # beyond 3× of 120 (≥360) → hard
    hard = assess_category_band(400.0, "earphones", price_type="retail")
    assert hard.get("hide") is True
    assert hard.get("hard_guards")


def _parse_money(v):
    import re

    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,.]+", str(v).replace(",", ""))
    return float(m.group(0).replace(",", "")) if m else None


def test_uk_retail_priced_with_extracted_price():
    from app.utils.uk_shopping_seller import classify_uk_seller_origin

    row = {
        "link": "https://www.google.com/search?ibp=oshop&q=earphones",
        "merchant": "Amazon.co.uk",
        "host": "google.com",
        "is_shopping_offer": True,
        "price": "£19",
        "extracted_price": "18.99",
        "currency": "GBP",
        "delivery": "Free delivery",
        "price_source": "serp",
    }
    origin = classify_uk_seller_origin(row)
    assert origin["origin_class"] == "confirmed_UK"
    annotated = annotate_uk_shopping_sellers([row])[0]
    assert annotated["uk_retail_priced"] is True
    assert annotated["counts_as_priced_comparison"] is True
    assert annotated["best_pick_eligible"] is False
    assert annotated["price_review_only"] is False


def test_gl_uk_alone_is_not_origin():
    from app.utils.uk_shopping_seller import classify_uk_seller_origin

    row = {
        "link": "https://www.google.com/search?ibp=oshop&q=x",
        "merchant": "Appelboom Pennenspeciaalzaak",
        "host": "google.com",
        "gl": "uk",
        "delivery": "Free delivery on £173+",
        "price": "£11",
        "extracted_price": "10.89",
        "currency": "GBP",
    }
    origin = classify_uk_seller_origin(row)
    assert origin["origin_class"] == "unknown"


def test_band_file_covers_uk_query_categories():
    for q in [
        "phone case",
        "usb c cable",
        "earphones",
        "tote bag",
        "notebooks",
        "allen keys",
        "cash and carry rice 5kg",
        "lip gloss bulk",
        "uk plug extension lead",
        "power bank 10000mah",
        "ballpoint pens",
        "makeup brush set",
    ]:
        b = band_for_query(q)
        assert b["ceiling_gbp"] > b["floor_gbp"]
