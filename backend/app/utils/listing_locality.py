"""Classify listings as local vs import by host / origin (not currency)."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.core.region_profile import (
    get_profile,
    import_origin_group,
    is_local_host,
)
from app.utils.cost_assumptions import infer_listing_origin


def listing_host(listing: dict[str, Any] | None) -> str:
    if not listing or not isinstance(listing, dict):
        return ""
    if listing.get("host"):
        return str(listing["host"]).strip().lower().removeprefix("www.")
    link = str(listing.get("link") or "")
    try:
        return urlparse(link).hostname.removeprefix("www.").lower()  # type: ignore[union-attr]
    except Exception:
        return ""


def classify_listing_locality(
    listing: dict[str, Any] | None,
    *,
    location: str | None = None,
    country_code: str | None = None,
    local_currency: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Local = UK(.co.uk / profile local_host_patterns) host OR domestic origin group.
    Currency mismatch does NOT demote a local host (USD on amazon.co.uk stays local).
    """
    prof = profile or get_profile(
        location=location, country_code=country_code, currency=local_currency
    )
    link = str((listing or {}).get("link") or "")
    host = listing_host(listing)
    local_by_host = bool(is_local_host(link or host, prof))
    origin = infer_listing_origin(listing, prof)
    group = import_origin_group(prof, origin)
    domestic = group == "domestic"
    is_local = local_by_host or domestic
    return {
        "host": host,
        "origin_country": origin,
        "origin_group": group,
        "local_by_host": local_by_host,
        "is_local": is_local,
        "is_import": not domestic,
    }


def annotate_listing_locality(
    listings: list[dict[str, Any]],
    *,
    location: str | None = None,
    country_code: str | None = None,
    local_currency: str | None = None,
) -> list[dict[str, Any]]:
    prof = get_profile(
        location=location, country_code=country_code, currency=local_currency
    )
    out: list[dict[str, Any]] = []
    for row in listings or []:
        item = dict(row)
        meta = classify_listing_locality(item, profile=prof)
        item["host"] = meta["host"] or item.get("host")
        item["origin_country"] = meta["origin_country"]
        item["is_local"] = meta["is_local"]
        item["local_by_host"] = meta["local_by_host"]
        # Keep duty import flag separate from display locality
        item["is_import"] = meta["is_import"]
        out.append(item)
    return out
