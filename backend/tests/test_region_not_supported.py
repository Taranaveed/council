"""Fix 1: unsupported country must not silently fall back to UK/PK."""
from __future__ import annotations

import pytest

from app.core.region_profile import (
    RegionNotSupportedError,
    get_profile,
    load_profile,
    resolve_profile_id,
    require_supported_profile,
)


def test_resolve_us_from_location_and_currency():
    assert resolve_profile_id(location="New York, United States") == "us"
    assert resolve_profile_id(currency="USD") == "us"
    assert resolve_profile_id(country_code="us") == "us"


def test_load_profile_us_raises_not_supported():
    with pytest.raises(RegionNotSupportedError) as ei:
        load_profile("us")
    assert ei.value.profile_id == "us"
    assert "not supported" in str(ei.value).lower()


def test_get_profile_us_buyer_raises_not_uk_fallback():
    with pytest.raises(RegionNotSupportedError):
        get_profile(location="New York, United States", currency="USD")
    with pytest.raises(RegionNotSupportedError):
        require_supported_profile(country_code="us")


def test_supported_uk_and_pk_still_load():
    assert get_profile(country_code="uk")["id"] == "uk"
    assert get_profile(location="Lahore, Pakistan")["id"] == "pk"
    assert get_profile(currency="GBP")["id"] == "uk"
    assert get_profile(currency="PKR")["id"] == "pk"


def test_no_silent_fallback_returns_uk_data_for_us():
    """Regression: previously load_profile('us') returned UK JSON rates."""
    with pytest.raises(RegionNotSupportedError):
        data = load_profile("us")
        # Must never reach here with UK rates
        assert data.get("id") != "uk"
