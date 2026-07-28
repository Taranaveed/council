"""Vendor website existence checks to reduce hallucinated 'premium' sellers."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

VendorStatus = Literal["Verified", "Unverified"]

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
    "apple.com",
    "sony.com",
    "samsung.com",
    "noon.",
    "flipkart.",
    "etsy.",
    "ikea.",
    "costco.",
    "microcenter.",
    "ebay.",
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


def _sanitize_vendor_slug(vendor_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", (vendor_name or "").lower())
    return slug[:48]


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


def _vendor_name_trusted(vendor_name: str) -> bool:
    blob = (vendor_name or "").strip().lower()
    if not blob:
        return False
    return any(name in blob for name in _TRUSTED_VENDOR_NAMES)


def _candidate_urls(vendor_name: str, link: str | None = None) -> list[str]:
    """Listing link first, then guessed vendor domains."""
    urls: list[str] = []
    if link and str(link).startswith("http"):
        urls.append(str(link).strip())

    slug = _sanitize_vendor_slug(vendor_name)
    if len(slug) >= 3:
        urls.extend(
            [
                f"https://www.{slug}.com",
                f"https://{slug}.com",
                f"https://www.{slug}.co.uk",
                f"https://www.{slug}.pk",
            ]
        )
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _url_is_alive(client: httpx.AsyncClient, url: str) -> bool:
    try:
        # HEAD first; some sites block HEAD → fall back to GET
        res = await client.head(url, follow_redirects=True)
        if res.status_code < 400:
            return True
        if res.status_code in (405, 403, 401):
            res = await client.get(url, follow_redirects=True)
            return res.status_code < 400
        return False
    except Exception:
        return False


def _host_looks_trusted(url: str) -> bool:
    host = _hostname(url)
    if not host:
        return False
    return any(h in host for h in _TRUSTED_HOST_HINTS)


async def checkVendorExistence(
    vendorName: str,
    link: str | None = None,
) -> VendorStatus:
    """
    Return 'Verified' if the vendor appears to have an active website (or a live listing URL),
    otherwise 'Unverified'.

    Prefer checking the listing `link` when available so we don't invent vendors.
    """
    name = (vendorName or "").strip()
    if not name and not link:
        return "Unverified"

    # Fast path: known marketplace name in vendor/source string
    if name and _vendor_name_trusted(name):
        return "Verified"

    # Fast path: known major hosts on the listing link
    if link and _host_looks_trusted(link):
        return "Verified"

    candidates = _candidate_urls(name, link)
    if not candidates:
        return "Unverified"

    timeout = httpx.Timeout(4.0, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "SyntheticFocusGroup/1.0"}) as client:
        # Always try the listing link first (even if host is not on the allowlist)
        for url in candidates[:4]:
            if await _url_is_alive(client, url):
                return "Verified"
    return "Unverified"


# Snake_case alias for Python call sites
async def check_vendor_existence(vendor_name: str, link: str | None = None) -> VendorStatus:
    return await checkVendorExistence(vendor_name, link)


async def enrich_listings_with_vendor_status(
    listings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach vendor_status Verified|Unverified to each listing (unique vendor+host checked once)."""
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

    # Bound concurrency
    sem = asyncio.Semaphore(5)

    async def run_one(item: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            status = await status_for(item)
        enriched = dict(item)
        enriched["vendor_status"] = status
        return enriched

    return list(await asyncio.gather(*[run_one(i) for i in listings]))
