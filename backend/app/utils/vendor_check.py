"""Vendor website existence checks to reduce hallucinated 'premium' sellers."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Literal
from urllib.parse import urlparse

VendorStatus = Literal["Known marketplace", "Unknown"]

# Known marketplace / retailer hosts we treat as having a real presence
_TRUSTED_HOST_HINTS = (
    "amazon.",
    "ebay.",
    "walmart.",
    "bestbuy.",
    "target.",
    "newegg.",
    "bhphotovideo.",
    "daraz.",
    "priceoye.",
    "homeshopping.",
    "telemart.",
    "shophive.",
    "mega.pk",
    "symbios.",
    "olx.",
    "gumtree.",
    "craigslist.",
    "alibaba.",
    "aliexpress.",
    "indiamart.",
    "made-in-china.",
    "dhgate.",
    "globalsources.",
    "tradeindia.",
    "europages.",
    "thomasnet.",
    "faire.",
    "apple.com",
    "sony.com",
    "samsung.com",
    "noon.",
    "flipkart.",
    "etsy.",
    "ikea.",
    "costco.",
    "microcenter.",
    "shopify.",
    "woocommerce.",
    "mercadolibre.",
    "rakuten.",
    "zalando.",
    "argos.",
    "johnlewis.",
    "currys.",
    "canadiantire.",
    "samsclub.",
    "macys.",
    "nordstrom.",
    "wayfair.",
    "overstock.",
    "wish.com",
    "shein.",
    "temu.",
    "lazada.",
    "shopee.",
    "tokopedia.",
    "takealot.",
    "jumia.",
    "fnac.",
    "cdiscount.",
    "bol.com",
    "mediamarkt.",
    "saturn.",
)

# Marketplace / brand names that appear in Serp `source` / vendor strings
_TRUSTED_VENDOR_NAMES = (
    "amazon",
    "ebay",
    "walmart",
    "best buy",
    "bestbuy",
    "target",
    "newegg",
    "daraz",
    "priceoye",
    "priceoye.pk",
    "homeshopping",
    "telemart",
    "shophive",
    "olx",
    "gumtree",
    "craigslist",
    "alibaba",
    "aliexpress",
    "indiamart",
    "made-in-china",
    "dhgate",
    "global sources",
    "tradeindia",
    "europages",
    "thomasnet",
    "faire",
    "apple",
    "sony",
    "samsung",
    "noon",
    "flipkart",
    "etsy",
    "ikea",
    "costco",
    "micro center",
    "microcenter",
    "lazada",
    "shopee",
    "tokopedia",
    "takealot",
    "jumia",
    "mercadolibre",
    "rakuten",
    "zalando",
    "argos",
    "john lewis",
    "currys",
    "wayfair",
    "shein",
    "temu",
    "fnac",
    "cdiscount",
    "media markt",
    "mediamarkt",
)


def is_known_marketplace_status(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s in ("known marketplace", "known_marketplace", "verified")


def _hostname(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return ""


def _cache_key(vendor_name: str, link: str | None) -> str:
    vendor = (vendor_name or "").strip().lower()
    host = _hostname(link)
    return f"{vendor}|{host}"


def _name_matches(blob: str, name: str) -> bool:
    name = (name or "").strip().lower()
    if not name or not blob:
        return False
    if blob == name:
        return True
    return re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", blob) is not None


def _vendor_name_trusted(vendor_name: str) -> bool:
    blob = (vendor_name or "").strip().lower()
    if not blob:
        return False
    return any(_name_matches(blob, name) for name in _TRUSTED_VENDOR_NAMES)


def _host_looks_trusted(url: str) -> bool:
    host = _hostname(url)
    if not host:
        return False
    host = host[4:] if host.startswith("www.") else host
    for hint in _TRUSTED_HOST_HINTS:
        h = hint.rstrip(".").lower()
        if host == h or host.startswith(h) or host.endswith("." + h):
            return True
    return False


async def checkVendorExistence(
    vendorName: str,
    link: str | None = None,
) -> VendorStatus:
    """
    Return 'Known marketplace' only when the listing host or vendor name matches
    a known marketplace. A live HTTP URL is NOT verification.
    """
    name = (vendorName or "").strip()
    if name and _vendor_name_trusted(name):
        return "Known marketplace"
    if link and _host_looks_trusted(link):
        return "Known marketplace"
    return "Unknown"


# Snake_case alias for Python call sites
async def check_vendor_existence(vendor_name: str, link: str | None = None) -> VendorStatus:
    return await checkVendorExistence(vendor_name, link)


async def enrich_listings_with_vendor_status(
    listings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach vendor_status Known marketplace|Unknown (unique vendor+host checked once)."""
    if not listings:
        return listings

    cache: dict[str, VendorStatus] = {}

    async def status_for(item: dict[str, Any]) -> VendorStatus:
        vendor = str(item.get("vendor") or item.get("source") or "").strip()
        link = item.get("link") or None
        key = _cache_key(vendor, link if isinstance(link, str) else None)
        if key in cache:
            return cache[key]
        status = await checkVendorExistence(vendor, link if isinstance(link, str) else None)
        cache[key] = status
        return status

    sem = asyncio.Semaphore(8)

    async def run_one(item: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            status = await status_for(item)
        enriched = dict(item)
        enriched["vendor_status"] = status
        return enriched

    return list(await asyncio.gather(*[run_one(i) for i in listings]))
