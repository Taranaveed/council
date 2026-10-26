"""Market cache key ignores qty/city; varies by mode/currency/country."""
from __future__ import annotations

from app.core.market_client import market_cache_key


def test_cache_key_ignores_qty_and_city():
    a = market_cache_key(
        "phone case",
        country_code="uk",
        preferred_currency="GBP",
        bulk_mode=True,
        location="London, United Kingdom",
    )
    b = market_cache_key(
        "phone case",
        country_code="uk",
        preferred_currency="GBP",
        bulk_mode=True,
        location="Manchester, United Kingdom",
    )
    # Same key even if callers would have passed different quantities —
    # quantity is not a parameter of market_cache_key at all.
    assert a == b
    assert "london" not in a
    assert "manchester" not in a
    assert "100" not in a
    assert "500" not in a


def test_cache_key_differs_by_mode_currency_country():
    base = dict(product_name="usb c cable", preferred_currency="GBP", bulk_mode=True)
    uk_bulk = market_cache_key(**base, country_code="uk")
    uk_retail = market_cache_key(
        "usb c cable", country_code="uk", preferred_currency="GBP", bulk_mode=False
    )
    uk_usd = market_cache_key(
        "usb c cable", country_code="uk", preferred_currency="USD", bulk_mode=True
    )
    pk_bulk = market_cache_key(
        "usb c cable", country_code="pk", preferred_currency="GBP", bulk_mode=True
    )
    assert uk_bulk != uk_retail
    assert uk_bulk != uk_usd
    assert uk_bulk != pk_bulk
    assert uk_bulk == "usb c cable|uk|bulk|GBP"
    assert uk_retail == "usb c cable|uk|retail|GBP"
    assert pk_bulk == "usb c cable|pk|bulk|GBP"
