"""HTTP client for the Node.js market-service."""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

import httpx

from app.core.region_config import resolve_market_locale

MARKET_SERVICE_URL = os.getenv("MARKET_SERVICE_URL", "http://localhost:3001").rstrip("/")
# Short TTL: speeds repeat searches without freezing debate (agents get a fresh run_id).
_CACHE_TTL_SEC = float(os.getenv("MARKET_CACHE_TTL_SEC", "90"))
_market_cache: dict[str, tuple[float, list[dict[str, Any]], str | None]] = {}


def _is_local_market_url() -> bool:
    return bool(re.search(r"localhost|127\.0\.0\.1", MARKET_SERVICE_URL, re.I))


def _cache_key(
    product_name: str,
    location: str | None,
    country_code: str | None,
    limit: int,
    preferred_currency: str | None,
    bulk_mode: bool = False,
    quantity: int | None = None,
    budget: str | None = None,
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
            "bulk" if bulk_mode else "retail",
            str(quantity or ""),
            (budget or "").strip().lower(),
        ]
    )


async def wake_market_service(timeout_sec: float = 90.0) -> bool:
    """Ping market /health until the free-tier service is awake."""
    if _is_local_market_url():
        timeout_sec = min(float(timeout_sec), 3.0)
    deadline = time.time() + timeout_sec
    delay = 0.35 if _is_local_market_url() else 1.5
    ping_timeout = 4.0 if _is_local_market_url() else 25.0
    while time.time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(ping_timeout, connect=3.0)) as client:
                res = await client.get(f"{MARKET_SERVICE_URL}/health")
                if res.status_code == 200:
                    return True
        except Exception as e:
            print(f"[market_client] wake ping: {e}")
        await asyncio.sleep(delay)
        delay = min(delay + (0.35 if _is_local_market_url() else 1.0), 1.5 if _is_local_market_url() else 4.0)
    return False


async def fetch_market_prices(
    product_name: str,
    location: str | None = None,
    country_code: str | None = None,
    limit: int = 10,
    preferred_currency: str | None = None,
    *,
    bulk_mode: bool = False,
    quantity: int | None = None,
    budget: str | None = None,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    """Call Node market service. Returns (listings, warning)."""
    key = _cache_key(
        product_name, location, country_code, limit, preferred_currency,
        bulk_mode, quantity, budget,
    )
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
        "limit": max(3, min(limit, 16)),
    }
    if bulk_mode:
        payload["bulkMode"] = True
        if quantity:
            payload["quantity"] = int(quantity)
        if budget and str(budget).strip():
            payload["budget"] = str(budget).strip()
    if preferred_currency and str(preferred_currency).strip():
        payload["preferredCurrency"] = str(preferred_currency).strip().upper()

    last_error: str | None = None
    # Free Render sleeps — wake quickly locally; longer only for remote hosts.
    await wake_market_service(75.0 if not _is_local_market_url() else 2.0)

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                res = await client.post(f"{MARKET_SERVICE_URL}/market/prices", json=payload)
                # Cold proxy sometimes returns HTML/404 while booting.
                if res.status_code in (404, 502, 503, 504):
                    last_error = f"Market service HTTP {res.status_code}"
                    print(f"[market_client] attempt {attempt}: {last_error}")
                    await asyncio.sleep(1.5 * attempt)
                    await wake_market_service(20.0 if not _is_local_market_url() else 2.0)
                    continue
                res.raise_for_status()
                data = res.json()
                # Empty list is a valid response — do not use `or` ( [] is falsy ).
                raw_listings = data.get("listings")
                if not isinstance(raw_listings, list):
                    raw_listings = data.get("results")
                if not isinstance(raw_listings, list):
                    last_error = (
                        str(data.get("warning") or "")
                        or "Unexpected market-service response"
                    )
                    print(f"[market_client] attempt {attempt}: non-list listings")
                    await asyncio.sleep(1.5 * attempt)
                    continue
                warn = str(data.get("warning") or "") or None
                if raw_listings:
                    _market_cache[key] = (time.time(), raw_listings, warn)
                return raw_listings, warn
        except Exception as e:
            last_error = str(e)
            print(f"[market_client] attempt {attempt} failed: {e}")
            await asyncio.sleep(1.5 * attempt)
            await wake_market_service(20.0 if not _is_local_market_url() else 2.0)

    return [], f"Market service unreachable: {last_error}"


async def fetch_page_facts_for_listings(
    listings: list[dict[str, Any]],
    *,
    query: str = "",
    preferred_currency: str | None = None,
    location: str | None = None,
    country_code: str | None = None,
) -> list[dict[str, Any]]:
    """Re-fetch top listing pages for warranty / policy / variants / price facts."""
    if not listings:
        return listings
    locale = resolve_market_locale(location, country_code)
    payload = {
        "listings": listings[:5],
        "query": query or "",
        "preferredCurrency": (preferred_currency or "").strip().upper() or None,
        "gl": locale.get("gl") or "us",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
            res = await client.post(f"{MARKET_SERVICE_URL}/market/page-facts", json=payload)
            if res.status_code != 200:
                return listings
            data = res.json()
            enriched = data.get("listings") or []
            if not isinstance(enriched, list) or not enriched:
                return listings
            by_link = {
                str(r.get("link") or "").strip(): r
                for r in enriched
                if isinstance(r, dict) and r.get("link")
            }
            out: list[dict[str, Any]] = []
            for row in listings:
                link = str(row.get("link") or "").strip()
                patch = by_link.get(link)
                out.append({**row, **patch} if patch else row)
            return out
    except Exception as e:
        print(f"[market_client] page-facts failed: {e}")
        return listings


async def fetch_tracked_listing_price(
    *,
    url: str,
    query: str,
    native_currency: str,
) -> dict[str, Any]:
    """Refresh exactly one saved listing URL; never substitute another seller."""
    payload = {
        "url": str(url or "").strip(),
        "query": str(query or "").strip(),
        "nativeCurrency": str(native_currency or "USD").upper(),
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=15.0)
        ) as client:
            res = await client.post(
                f"{MARKET_SERVICE_URL}/market/watch-price", json=payload
            )
            if res.status_code != 200:
                return {
                    "available": False,
                    "reason": "fetch_error",
                    "status_code": res.status_code,
                }
            data = res.json()
            return data if isinstance(data, dict) else {
                "available": False,
                "reason": "bad_response",
            }
    except Exception as exc:
        return {
            "available": False,
            "reason": "fetch_error",
            "error": str(exc)[:200],
        }


def format_market_block(
    listings: list[dict[str, Any]],
    *,
    preferred_currency: str | None = None,
    bulk_mode: bool = False,
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
        "(vendor_status is Known marketplace or Unknown — Known marketplace means a familiar host, "
        "NOT a verified seller. Do NOT invent premium/mall vendors that are not listed here):",
    ]
    if cur:
        lines.append(f"Seller's working currency: {cur}. Prefer listings already priced in {cur}.")
    alibaba = [
        i for i in listings
        if any(
            h in str(i.get("link") or i.get("vendor") or "").lower()
            for h in (
                "alibaba.", "indiamart.", "made-in-china.", "dhgate.",
                "globalsources.", "tradeindia.", "aliexpress.", "europages.",
                "thomasnet.", "faire.",
            )
        )
    ]
    if bulk_mode:
        pick = next((i for i in listings if i.get("best_pick")), listings[0] if listings else None)
        lines.append(
            "BULK SOURCE: Listings are ranked for this buyer's region, quantity, and budget. "
            "Compare factory quotes (often USD) as unit cost + shipping, not as local retail. "
            "price_local_approx is an approximate display conversion — NEVER treat $0.59 as 1:1 local currency. "
            "Use only price_local_approx from each row. "
            "Do not invent seller ratings, years in business, HS codes, or exact customs %. "
            "Prefer the RANKED PICK unless a safety issue outweighs price. "
            "Ask MOQ, lead time, sample, and payment terms before wiring money."
        )
        if pick:
            reason = pick.get("pick_reason") or "best cheap fit for region and quantity"
            lines.append(
                f"RANKED PICK: {pick.get('vendor') or 'supplier'} | {pick.get('price') or 'n/a'} | "
                f"{pick.get('title') or ''} | {reason} | {pick.get('link') or ''}"
            )
        if alibaba:
            names = sorted({
                str(i.get("vendor") or "supplier") for i in alibaba
            })
            lines.append(f"Wholesale platforms in this run ({len(alibaba)} listings): {', '.join(names[:8])}.")
        else:
            lines.append("No wholesale supplier pages in this run — say so; do not invent factory sellers.")
    if foreign and not local and not bulk_mode:
        lines.append(
            "CURRENCY WARNING: ALL live listings are in a FOREIGN currency. "
            "They are international reference only — NOT local market prices. "
            "Do NOT treat a USD/$ price as a local median. "
            f"Anchor recommended_price inside the seller's stated {cur or 'local'} band "
            "and clearly say local comps were missing."
        )
    elif foreign and not bulk_mode:
        lines.append(
            "CURRENCY NOTE: Some listings are foreign-currency (international reference). "
            f"Weight {cur or 'local'}-currency comps much more heavily."
        )

    for i, item in enumerate(listings, 1):
        title = item.get("title", "Unknown")
        price = item.get("price", "N/A")
        vendor = item.get("vendor") or item.get("source", "Unknown")
        link = item.get("link", "")
        status = item.get("vendor_status") or "Unknown"
        source = item.get("price_source") or "serp"
        mismatch = " FOREIGN" if item.get("currency_mismatch") else ""
        approx = item.get("price_local_approx")
        approx_bit = f" | local_approx={approx}" if approx else ""
        pick_bit = " BEST_PICK" if item.get("best_pick") else ""
        origin = item.get("supplier_origin") or ""
        origin_bit = f" | origin={origin}" if origin else ""
        moq = item.get("moq")
        moq_src = str(item.get("moq_source") or "")
        if moq is not None and moq_src.lower() not in (
            "not_on_snippet",
            "not_verified",
            "assumed_1_from_page_price",
            "missing",
            "",
        ) and not moq_src.lower().startswith("not_"):
            moq_bit = f" | MOQ={moq} (source={moq_src or 'listing'})"
        else:
            moq_bit = " | MOQ=not_confirmed"
        wt = item.get("package_weight_kg")
        wt_from_page = bool(item.get("package_weight_source") == "page" or item.get("weight_from_page"))
        if wt is not None and wt_from_page:
            wt_bit = f" | weight_kg={wt} (page)"
        elif wt is not None:
            wt_bit = " | weight_kg=assumed_not_confirmed"
        else:
            wt_bit = ""
        tiers = item.get("price_tiers") if isinstance(item.get("price_tiers"), list) else []
        tier_bit = ""
        if tiers and str(item.get("price_source") or "").lower() in ("page", "tier", "tier_selected", "page_scalar"):
            bits = []
            for t in tiers[:4]:
                if not isinstance(t, dict):
                    continue
                bits.append(f"{t.get('min_qty')}+ @ {t.get('unit_price')}")
            if bits:
                tier_bit = f" | tiers=[{'; '.join(bits)}]"
        elif tiers:
            tier_bit = " | tiers=unverified_serp_do_not_use_as_primary"
        product_bit = ""
        if item.get("is_product_page") is False or item.get("unit_price_rejected"):
            product_bit = " | UNIT_PRICE_REJECTED=storefront"
        elif str(item.get("price_source") or "").lower() in ("serp", "snippet"):
            product_bit = " | unit_price_unverified=serp"
        lines.append(
            f"{i}. {title} | {price}{approx_bit} | vendor={vendor} | status={status} | "
            f"price_source={source}{mismatch}{pick_bit}{origin_bit}{moq_bit}{wt_bit}{tier_bit}"
            f"{product_bit} | {link}"
        )
    lines.append(
        "RULE: Prefer Known marketplace hosts and local-currency prices. "
        "Known marketplace is not seller identity verification. "
        "Use only vendors/prices listed above for market_context. "
        "Challenge claims about Unknown hosts that sound like premium authorized stores without evidence. "
        "If this is a bulk run, start from the RANKED PICK (best cheap supplier for region/qty/budget) "
        "unless a local option is clearly safer and still affordable. "
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
                "vendor_status": item.get("vendor_status") or "Unknown",
                "price_source": item.get("price_source") or "serp",
                "currency": item.get("currency"),
                "currency_mismatch": bool(item.get("currency_mismatch")),
                "price_local_approx": item.get("price_local_approx"),
                "best_pick": bool(item.get("best_pick")),
                "pick_reason": item.get("pick_reason"),
                "supplier_id": item.get("supplier_id"),
                "supplier_origin": item.get("supplier_origin"),
            }
        )
    return rows
