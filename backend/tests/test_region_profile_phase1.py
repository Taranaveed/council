"""Phase 0/1 RegionProfile — PK golden parity, duty lookup, VAT, UK defaults."""
from __future__ import annotations

import pytest

from app.core.region_profile import (
    assert_pk_golden_parity,
    get_profile,
    import_origin_group,
    load_profile,
    lookup_duty,
)
from app.utils.cost_assumptions import shared_cost_assumptions
from app.utils.landed_cost import compute_landed_cost


def test_pk_golden_parity_frozen():
    pk = assert_pk_golden_parity()
    assert pk["id"] == "pk"
    assert pk["serp"]["shopping_gl_supported"] is False


def test_uk_profile_schema():
    uk = load_profile("uk")
    assert uk["version"] == "region_uk_v1"
    assert uk["trade_zone"] == "UK"
    assert uk["currency"] == "GBP"
    assert uk["serp"]["shopping_gl_supported"] is True
    assert uk["serp"]["site_tld_pass"] == ".co.uk"
    assert "EU" in uk["import_origin_groups"]["import"]
    assert "CN" in uk["import_origin_groups"]["import"]
    assert "ROW" in uk["import_origin_groups"]["import"]
    assert uk["duty"]["fallback"]["effective_date"]
    assert uk["duty"]["fallback"]["source_url"]
    assert uk["sales_tax"]["effective_date"]
    assert uk["freight_usd_per_kg"]["source_url"]


def test_uk_treats_eu_cn_row_as_import():
    uk = load_profile("uk")
    assert import_origin_group(uk, "EU") == "import"
    assert import_origin_group(uk, "CN") == "import"
    assert import_origin_group(uk, "US") == "import"
    assert import_origin_group(uk, "UK") == "domestic"
    assert import_origin_group(uk, "GB") == "domestic"
    assert import_origin_group(uk, "JP") == "import"  # ROW catch-all


def test_duty_lookup_fallback_labeled():
    pk = load_profile("pk")
    row = lookup_duty(pk, commodity_code=None, origin_country="CN")
    assert row["used_fallback"] is True
    assert row["matched"] is False
    assert float(row["rate_mid"]) == 0.25
    assert row.get("effective_date")
    assert row.get("source_url")
    assert "fallback" in str(row.get("label") or "").lower() or "assumption" in str(
        row.get("label") or ""
    ).lower()


def test_duty_lookup_exact_match():
    pk = dict(load_profile("pk"))
    pk["duty"] = {
        "fallback": pk["duty"]["fallback"],
        "lookup": [
            {
                "destination": "pk",
                "commodity_code": "8518",
                "origin_country": "CN",
                "rate_mid": 0.11,
                "rate_low": 0.05,
                "rate_high": 0.18,
                "effective_date": "2026-01-01",
                "source_url": "assumption://test-hs",
                "label": "test HS row",
            }
        ],
    }
    row = lookup_duty(pk, commodity_code="8518", origin_country="CN")
    assert row["matched"] is True
    assert float(row["rate_mid"]) == 0.11


def test_buyer_vat_registered_omits_tax():
    with_tax = shared_cost_assumptions(
        local_currency="GBP",
        foreign_factory=True,
        country_code="uk",
        buyer_vat_registered=False,
    )
    no_tax = shared_cost_assumptions(
        local_currency="GBP",
        foreign_factory=True,
        country_code="uk",
        buyer_vat_registered=True,
    )
    assert with_tax["sales_tax_rate"] == 0.2
    assert no_tax["sales_tax_rate"] == 0.0
    assert no_tax["buyer_vat_registered"] is True
    assert no_tax["sales_tax_meta"]["rate_if_not_registered"] == 0.2


def test_pk_landed_cost_parity_rates():
    """PK rates must stay identical when currency/location resolve to pk."""
    shared = shared_cost_assumptions(
        local_currency="PKR",
        foreign_factory=True,
        location="Lahore, Pakistan",
        country_code="pk",
    )
    assert shared["profile_id"] == "pk"
    assert shared["trade_zone"] == "PK"
    assert shared["duty_rate_mid"] == 0.25
    assert shared["sales_tax_rate"] == 0.18
    assert shared["freight_usd_per_kg_mid"] == 10.0
    assert shared["duty_meta"]["effective_date"]
    assert shared["sales_tax_meta"]["source_url"]

    listing = {
        "title": "Factory earbuds",
        "price": "$2.00",
        "link": "https://www.alibaba.com/product-detail/x.html",
        "supplier_origin": "CN",
        "price_source": "page",
        "is_product_page": True,
        "package_weight_kg": 0.1,
        "package_weight_source": "page",
    }
    landed = compute_landed_cost(
        listing,
        quantity=100,
        local_currency="PKR",
        cost_assumptions=shared,
        location="Lahore, Pakistan",
        country_code="pk",
        buyer_vat_registered=False,
    )
    assert landed is not None
    assert landed["duty_rate"] == 0.25
    assert landed["sales_tax_rate"] == 0.18
    assert landed["profile_id"] == "pk"


def test_get_profile_default_resolves_without_crash():
    # Env default may be uk; currency PKR still pins golden fixture
    assert get_profile(currency="PKR")["id"] == "pk"
    assert get_profile(country_code="uk")["id"] == "uk"


def test_us_no_longer_silently_loads_uk():
    from app.core.region_profile import RegionNotSupportedError

    with pytest.raises(RegionNotSupportedError):
        get_profile(country_code="us")
