"""HTTP client for the Node.js market-service."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from app.core.region_config import resolve_market_locale

MARKET_SERVICE_URL = os.getenv("MARKET_SERVICE_URL", "http://localhost:3001").rstrip("/")
_CACHE_TTL_SEC = float(os.getenv("MARKET_CACHE_TTL_SEC", "600"))
_market_cache: dict[str, tuple[float, list[dict[str, Any]], str | None]] = {}


def _cache_key(
    product_name: str,
    location: str | None,
    country_code: str | None,
    limit: int,
    preferred_currency: str | None,
) -> str:
    locale = resolve_market_locale(location, country_code)
    cur = (preferred_currency or "").strip().upper()
    return "|".join(
        [
            (product_name or "").strip().lower(),
            locale["location"].lower(),
            locale["gl"].lower(),
            str(limit),
            cur,
        ]
    )


async def wake_market_service(timeout_sec: float = 90.0) -> bool:
    """Ping market /health until the free-tier service is awake."""
    deadline = time.time() + timeout_sec
    delay = 1.5
    while time.time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
                res = await client.get(f"{MARKET_SERVICE_URL}/health")
                if res.status_code == 200:
                    return True
        except Exception as e:
            print(f"[market_client] wake ping: {e}")
        await asyncio.sleep(delay)
        delay = min(delay + 1.0, 4.0)
    return False


async def fetch_market_prices(
    product_name: str,
    location: str | None = None,
    country_code: str | None = None,
    limit: int = 8,
    preferred_currency: str | None = None,
    *,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    """Call Node market service. Returns (listings, warning)."""
    key = _cache_key(product_name, location, country_code, limit, preferred_currency)
    if use_cache and key in _market_cache:
        ts, listings, warning = _market_cache[key]
        if time.time() - ts <= _CACHE_TTL_SEC and listings:
            return [dict(x) for x in listings], warning

    locale = resolve_market_locale(location, country_code)
    payload: dict[str, Any] = {
        "productName": product_name,
        "location": locale["location"],
        "countryCode": locale["country_code"],
        "gl": locale["gl"],
        "hl": locale["hl"],
        "limit": max(3, min(limit, 12)),
    }
    if preferred_currency and str(preferred_currency).strip():
        payload["preferredCurrency"] = str(preferred_currency).strip().upper()

    last_error: str | None = None
    # Free Render sleeps — wake + a few retries before giving up.
    await wake_market_service(75.0)

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
                res = await client.post(f"{MARKET_SERVICE_URL}/market/prices", json=payload)
                # Cold proxy sometimes returns HTML/404 while booting.
                if res.status_code in (404, 502, 503, 504):
                    last_error = f"Market service HTTP {res.status_code}"
                    print(f"[market_client] attempt {attempt}: {last_error}")
                    await asyncio.sleep(2 * attempt)
                    await wake_market_service(30.0)
                    continue
                res.raise_for_status()
                data = res.json()
                listings = data.get("listings") or data.get("results") or data
                warning = data.get("warning")
                if isinstance(listings, list):
                    warn = str(warning) if warning else None
                    if listings:
                        _market_cache[key] = (time.time(), listings, warn)
                    return listings, warn
                last_error = str(warning) if warning else "Unexpected market-service response"
        except Exception as e:
            last_error = str(e)
            print(f"[market_client] attempt {attempt} failed: {e}")
            await asyncio.sleep(2 * attempt)
            await wake_market_service(30.0)

    return [], f"Market service unreachable: {last_error}"


def format_market_block(
    listings: list[dict[str, Any]],
    *,
    preferred_currency: str | None = None,
) -> str:
    if not listings:
        return (
            "LIVE MARKET SYNC FAILED — no listings were retrieved from SerpApi/market-service.\n"
            "This does NOT mean the real-world market has no options.\n"
            "Do NOT invent vendors, prices, or claim the local market is empty.\n"
            "If you recommend PASS, reason MUST be: insufficient live listing data to verify a deal "
            "(data outage), NOT that trustworthy options do not exist in the buyer's city/country."
        )
    cur = (preferred_currency or "").strip().upper()
    foreign = [i for i in listings if i.get("currency_mismatch")]
    local = [i for i in listings if not i.get("currency_mismatch")]

    lines = [
        "Live market listings from search + seller websites "
        "(vendor_status is Verified or Unverified — do NOT invent "
        "premium/mall vendors that are not listed here):",
    ]
    if cur:
        lines.append(f"Seller's working currency: {cur}. Prefer listings already priced in {cur}.")
    if foreign and not local:
        lines.append(
            "CURRENCY WARNING: ALL live listings are in a FOREIGN currency. "
            "They are international reference only — NOT local market prices. "
            "Do NOT treat a USD/$ price as a local median. "
            f"Anchor recommended_price inside the seller's stated {cur or 'local'} band "
            "and clearly say local comps were missing."
        )
    elif foreign:
        lines.append(
            "CURRENCY NOTE: Some listings are foreign-currency (international reference). "
            f"Weight {cur or 'local'}-currency comps much more heavily."
        )

    for i, item in enumerate(listings, 1):
        title = item.get("title", "Unknown")
        price = item.get("price", "N/A")
        vendor = item.get("vendor") or item.get("source", "Unknown")
        link = item.get("link", "")
        status = item.get("vendor_status") or "Unverified"
        source = item.get("price_source") or "serp"
        mismatch = " FOREIGN" if item.get("currency_mismatch") else ""
        approx = item.get("price_local_approx")
        approx_bit = f" | local_approx={approx}" if approx else ""
        lines.append(
            f"{i}. {title} | {price}{approx_bit} | vendor={vendor} | status={status} | "
            f"price_source={source}{mismatch} | {link}"
        )
    lines.append(
        "RULE: Prefer Verified vendors and local-currency prices. "
        "Use only vendors/prices listed above for market_context. "
        "Challenge or discount claims about Unverified sellers "
        "that sound like premium authorized stores without evidence. "
        "If at least one Verified listing is within budget, lean BUY with verification steps — "
        "do not PASS solely because other listings are Unverified. "
        "Never present a converted foreign price as if it were a live local listing."
    )
    return "\n".join(lines)


def listings_to_market_context(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build comparison-table rows from live listings (never invent sellers)."""
    rows: list[dict[str, Any]] = []
    for item in listings:
        rows.append(
            {
                "vendor": item.get("vendor") or item.get("source") or "Unknown",
                "price": item.get("price") or "N/A",
                "title": item.get("title") or "",
                "link": item.get("link") or "",
                "vendor_status": item.get("vendor_status") or "Unverified",
                "price_source": item.get("price_source") or "serp",
                "currency": item.get("currency"),
                "currency_mismatch": bool(item.get("currency_mismatch")),
                "price_local_approx": item.get("price_local_approx"),
            }
        )
    return rows
