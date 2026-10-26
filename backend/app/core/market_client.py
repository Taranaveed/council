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
MARKET_SERVICE_SECRET = (os.getenv("MARKET_SERVICE_SECRET") or "").strip()
# Short TTL: speeds repeat searches without freezing debate (agents get a fresh run_id).
_CACHE_TTL_SEC = float(os.getenv("MARKET_CACHE_TTL_SEC", "90"))


def _market_headers() -> dict[str, str]:
    if not MARKET_SERVICE_SECRET:
        return {}
    return {"X-Market-Secret": MARKET_SERVICE_SECRET}
# value: (ts, listings, warning, listings_raw)
_market_cache: dict[
    str, tuple[float, list[dict[str, Any]], str | None, list[dict[str, Any]]]
] = {}
# When True, never call live market-service — miss returns empty + warning.
_fixture_replay: bool = False


def set_fixture_replay(enabled: bool, *, ttl_sec: float | None = None) -> None:
    """Lock market fetches to seeded cache only (benchmark --full --replay)."""
    global _fixture_replay, _CACHE_TTL_SEC
    _fixture_replay = bool(enabled)
    if ttl_sec is not None:
        _CACHE_TTL_SEC = float(ttl_sec)


def clear_market_cache() -> None:
    _market_cache.clear()


def seed_market_cache(
    *,
    product_name: str,
    country_code: str | None = None,
    preferred_currency: str | None = None,
    bulk_mode: bool = False,
    location: str | None = None,
    listings: list[dict[str, Any]] | None = None,
    warning: str | None = None,
    listings_raw: list[dict[str, Any]] | None = None,
) -> str:
    """
    Inject a recorded fixture into the in-process TTL cache.
    Empty listings are valid (NO_MATCH / zero usable) for fixture replay.
    """
    key = market_cache_key(
        product_name,
        country_code=country_code,
        preferred_currency=preferred_currency,
        bulk_mode=bulk_mode,
        location=location,
    )
    _market_cache[key] = (
        time.time(),
        [dict(x) for x in (listings or [])],
        warning,
        [dict(x) for x in (listings_raw or [])],
    )
    return key


def _is_local_market_url() -> bool:
    return bool(re.search(r"localhost|127\.0\.0\.1", MARKET_SERVICE_URL, re.I))


def market_cache_key(
    product_name: str,
    *,
    country_code: str | None = None,
    preferred_currency: str | None = None,
    bulk_mode: bool = False,
    location: str | None = None,
) -> str:
    """
    Cache key = query + country locale (gl) + mode + currency.
    Intentionally ignores city/location string, order quantity, limit, and budget.
    Qty-dependent MOQ/tier choice must run AFTER cache on the shared payload.
    """
    locale = resolve_market_locale(None, country_code or resolve_market_locale(location, None)["gl"])
    cur = (preferred_currency or "").strip().upper()
    return "|".join(
        [
            (product_name or "").strip().lower(),
            locale["gl"].lower(),
            "bulk" if bulk_mode else "retail",
            cur,
        ]
    )


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
    # limit/quantity/budget/location kept in signature for callers; ignored in key.
    del limit, quantity, budget
    return market_cache_key(
        product_name,
        country_code=country_code,
        preferred_currency=preferred_currency,
        bulk_mode=bulk_mode,
        location=location,
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
                res = await client.get(
                    f"{MARKET_SERVICE_URL}/health", headers=_market_headers()
                )
                if res.status_code == 200:
                    return True
        except Exception as e:
            print(f"[market_client] wake ping: {e}")
        await asyncio.sleep(delay)
        delay = min(delay + (0.35 if _is_local_market_url() else 1.0), 1.5 if _is_local_market_url() else 4.0)
    return False


# Last fetch meta for callers that need SerpApi search counts (benchmark).
_last_fetch_meta: dict[str, Any] = {
    "serpapi_searches": 0,
    "serpapi_stats": {
        "attempts": 0,
        "retries": 0,
        "successes": 0,
        "failures": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_unknown": 0,
    },
    "serpapi_search_log": [],
    "from_cache": False,
    "listings_raw": [],
    "cache_key": None,
}


def get_last_market_fetch_meta() -> dict[str, Any]:
    return dict(_last_fetch_meta)


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
    """Call Node market service. Returns (listings, warning).

    Order quantity is intentionally NOT sent to market-service: MOQ / tier
    selection and landed math apply quantity after this cacheable fetch
    (see compute_landed_cost / select_tier_for_quantity).
    """
    global _last_fetch_meta
    # quantity/budget ignored for fetch+cache (post-cache qty path).
    _ = quantity, budget
    key = _cache_key(
        product_name, location, country_code, limit, preferred_currency,
        bulk_mode, None, None,
    )
    if use_cache and key in _market_cache:
        ts, listings, warning, cached_raw = _market_cache[key]
        fresh = time.time() - ts <= _CACHE_TTL_SEC
        # Empty listings are valid hits under fixture replay (recorded NO_MATCH)
        # or when a warning / raw payload was stored with the entry.
        allow_empty = _fixture_replay or warning is not None or bool(cached_raw)
        if fresh and (listings or allow_empty):
            _last_fetch_meta = {
                "serpapi_searches": 0,
                "serpapi_stats": {
                    "attempts": 0,
                    "retries": 0,
                    "successes": 0,
                    "failures": 0,
                    "cache_hits": 1,
                    "cache_misses": 0,
                    "cache_unknown": 0,
                    "client_from_cache": True,
                },
                "serpapi_search_log": [
                    {
                        "label": "market_client_ttl_cache",
                        "attempt": 1,
                        "ok": True,
                        "cache_hit": True,
                        "search_id": None,
                        "status": "client_cache",
                        "total_time_taken": None,
                    }
                ],
                "from_cache": True,
                "listings_raw": [dict(x) for x in (cached_raw or [])],
                "cache_key": key,
            }
            return [dict(x) for x in listings], warning

    if _fixture_replay:
        _last_fetch_meta = {
            "serpapi_searches": 0,
            "serpapi_stats": {
                "attempts": 0,
                "retries": 0,
                "successes": 0,
                "failures": 0,
                "cache_hits": 0,
                "cache_misses": 1,
                "cache_unknown": 0,
                "client_from_cache": False,
            },
            "serpapi_search_log": [],
            "from_cache": False,
            "listings_raw": [],
            "cache_key": key,
        }
        return [], "Fixture replay: no seeded market cache for this query"

    locale = resolve_market_locale(location, country_code)
    # Country-level location for Serp so city variants share one fetch.
    try:
        from app.core.region_profile import get_profile

        prof = get_profile(
            location=location,
            country_code=country_code or locale["gl"],
            currency=preferred_currency,
        )
        serp = prof.get("serp") if isinstance(prof.get("serp"), dict) else {}
        fetch_location = str(serp.get("default_location") or locale["location"])
    except Exception:
        fetch_location = locale["location"]

    payload: dict[str, Any] = {
        "productName": product_name,
        "location": fetch_location,
        "countryCode": locale["country_code"],
        "gl": locale["gl"],
        "hl": locale["hl"],
        "limit": max(3, min(limit, 16)),
    }
    if bulk_mode:
        payload["bulkMode"] = True
        # Do not pass quantity — keeps payload qty-agnostic for cache reuse.
    if preferred_currency and str(preferred_currency).strip():
        payload["preferredCurrency"] = str(preferred_currency).strip().upper()

    last_error: str | None = None
    # Free Render sleeps — wake quickly locally; longer only for remote hosts.
    await wake_market_service(75.0 if not _is_local_market_url() else 2.0)

    # Extra attempts for cold-start 429s on free Render (wake floods the instance).
    max_attempts = 5 if not _is_local_market_url() else 3
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                res = await client.post(
                    f"{MARKET_SERVICE_URL}/market/prices",
                    json=payload,
                    headers=_market_headers(),
                )
                # Cold proxy / free-tier rate limit while booting.
                if res.status_code in (404, 429, 502, 503, 504):
                    last_error = f"Market service HTTP {res.status_code}"
                    print(f"[market_client] attempt {attempt}: {last_error}")
                    # 429 needs a longer cool-down than 502/503 — avoid stampede.
                    cool = (6.0 * attempt) if res.status_code == 429 else (1.5 * attempt)
                    await asyncio.sleep(cool)
                    await wake_market_service(25.0 if not _is_local_market_url() else 2.0)
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
                searches = data.get("serpapi_searches")
                if searches is None and isinstance(data.get("locale"), dict):
                    searches = data["locale"].get("serpapi_searches")
                try:
                    searches_n = int(searches or 0)
                except (TypeError, ValueError):
                    searches_n = 0
                pre_filter = data.get("listings_raw")
                if not isinstance(pre_filter, list):
                    pre_filter = []
                stats = data.get("serpapi_stats") if isinstance(data.get("serpapi_stats"), dict) else {}
                search_log = data.get("serpapi_search_log")
                if not isinstance(search_log, list):
                    search_log = []
                _last_fetch_meta = {
                    "serpapi_searches": searches_n,
                    "serpapi_stats": {
                        "attempts": int(stats.get("attempts") or searches_n or 0),
                        "retries": int(stats.get("retries") or 0),
                        "successes": int(stats.get("successes") or 0),
                        "failures": int(stats.get("failures") or 0),
                        "cache_hits": int(stats.get("cache_hits") or 0),
                        "cache_misses": int(stats.get("cache_misses") or 0),
                        "cache_unknown": int(stats.get("cache_unknown") or 0),
                        "client_from_cache": False,
                    },
                    "serpapi_search_log": search_log,
                    "from_cache": False,
                    "listings_raw": pre_filter,
                    "cache_key": key,
                }
                if raw_listings:
                    _market_cache[key] = (
                        time.time(),
                        raw_listings,
                        warn,
                        list(pre_filter),
                    )
                return raw_listings, warn
        except Exception as e:
            last_error = str(e)
            print(f"[market_client] attempt {attempt} failed: {e}")
            cool = 6.0 * attempt if "429" in last_error else 1.5 * attempt
            await asyncio.sleep(cool)
            await wake_market_service(25.0 if not _is_local_market_url() else 2.0)

    _last_fetch_meta = {
        "serpapi_searches": 0,
        "from_cache": False,
        "listings_raw": [],
        "cache_key": key,
    }
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
            res = await client.post(
                f"{MARKET_SERVICE_URL}/market/page-facts",
                json=payload,
                headers=_market_headers(),
            )
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
