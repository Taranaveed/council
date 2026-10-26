"""Local count uses host/origin — not currency_mismatch."""
from __future__ import annotations

from app.core.region_profile import get_profile
from app.utils.listing_locality import (
    annotate_listing_locality,
    classify_listing_locality,
)


def test_usd_priced_co_uk_listing_counts_as_local_under_uk_request():
    listing = {
        "title": "USB-C cable 1m",
        "link": "https://www.amazon.co.uk/dp/B0TESTUSD",
        "price": "$4.99",
        "currency": "USD",
        "currency_mismatch": True,  # must NOT demote locality
        "vendor": "Amazon UK",
    }
    meta = classify_listing_locality(
        listing, country_code="uk", local_currency="GBP"
    )
    assert meta["local_by_host"] is True
    assert meta["is_local"] is True
    assert meta["host"] == "amazon.co.uk"


def test_alibaba_cn_is_import_not_local():
    listing = {
        "title": "Factory tote bag",
        "link": "https://www.alibaba.com/product-detail/foo.html",
        "price": "$3.50",
        "currency": "USD",
        "supplier_origin": "CN",
        "vendor": "Alibaba",
    }
    meta = classify_listing_locality(listing, country_code="uk", local_currency="GBP")
    assert meta["is_local"] is False
    assert meta["is_import"] is True
    assert meta["origin_country"] == "CN"


def test_annotate_preserves_local_despite_mismatch():
    rows = annotate_listing_locality(
        [
            {
                "link": "https://www.ebay.co.uk/itm/123",
                "price": "$12.00",
                "currency_mismatch": True,
            }
        ],
        country_code="uk",
        local_currency="GBP",
    )
    assert rows[0]["is_local"] is True
    assert rows[0]["currency_mismatch"] is True
    prof = get_profile(country_code="uk")
    assert prof["id"] == "uk"
