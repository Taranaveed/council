"""
Shared market-listing prep for deal-finder and the UK benchmark runner.

Keeps UK Shopping annotate + raw→priced merge + locality in ONE place so
production and replay share the same rows before relevance / landed.
"""
from __future__ import annotations

from typing import Any

from app.utils.listing_channel import annotate_listing_channels
from app.utils.listing_locality import annotate_listing_locality
from app.utils.uk_shopping_seller import (
    annotate_price_types,
    annotate_uk_shopping_sellers,
)


def prepare_market_listings(
    listings: list[dict[str, Any]] | None,
    listings_raw: list[dict[str, Any]] | None,
    *,
    query: str,
    location: str | None,
    country_code: str | None,
    local_currency: str | None,
    is_bulk: bool,
) -> list[dict[str, Any]]:
    """
    Annotate channels/locality/UK sellers/price types, then merge priced UK
    retail comps from listings_raw into the comparison pool.
    Stamps `_benchmark_query` so category/order caps run in landed_cost.
    """
    rows = annotate_listing_channels(list(listings or []), is_bulk=is_bulk)
    rows = annotate_listing_locality(
        rows,
        location=location,
        country_code=country_code,
        local_currency=local_currency,
    )
    rows = annotate_uk_shopping_sellers(rows)
    rows = annotate_price_types(rows)

    raw_labeled = annotate_price_types(
        annotate_uk_shopping_sellers(
            annotate_listing_locality(
                annotate_listing_channels(list(listings_raw or []), is_bulk=is_bulk),
                location=location,
                country_code=country_code,
                local_currency=local_currency,
            )
        )
    )
    seen: set[str] = {str(x.get("link") or x.get("title") or "") for x in rows}
    for x in raw_labeled:
        if not x.get("uk_retail_priced"):
            continue
        k = str(x.get("link") or x.get("title") or "")
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        rows.append(x)

    q = str(query or "").strip()
    for item in rows:
        if q:
            item["_benchmark_query"] = q
            item.setdefault("query", q)
        # Origin-class locality: confirmed_UK = local; others not assumed local
        oc = str(item.get("uk_origin_class") or "")
        if oc == "confirmed_UK":
            item["is_local"] = True
            item["is_import"] = False
            item["origin_country"] = "UK"
        elif oc in ("likely_UK", "sells_to_UK_only", "unknown") and item.get(
            "uk_retail_priced"
        ):
            item["is_local"] = False
            item["is_import"] = True

    return rows


def rewrite_market_warning_for_priced(
    warning: str | None,
    *,
    priced_count: int,
    source_status: list[dict[str, Any]] | None = None,
) -> str | None:
    """
    Drop the misleading “zero usable seller prices” line when priced rows exist.
    Prefer a short summary of per-source status when provided.
    """
    w = (warning or "").strip()
    if priced_count > 0 and w:
        w = w.replace(
            "SerpApi returned zero usable seller prices for this query (gl=uk)",
            "",
        ).replace(
            "SerpApi returned zero usable seller prices for this query",
            "",
        )
        w = " ".join(w.split()).strip(" .")
    bits: list[str] = []
    if source_status:
        parts = []
        for s in source_status:
            label = str(s.get("label") or s.get("source") or "?")
            st = str(s.get("status") or ("ok" if s.get("ok") else "fail"))
            parts.append(f"{label}:{st}")
        if parts:
            bits.append("Serp sources — " + "; ".join(parts[:8]))
    if w:
        bits.append(w)
    if priced_count == 0 and not any("zero usable" in (b or "").lower() for b in bits):
        if not w:
            bits.append("No priced usable listings after filters.")
    return " ".join(bits).strip() or None


def source_status_from_serp_log(
    serp_search_log: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Normalize serpapi_search_log into per-source ok/timeout/empty status rows."""
    out: list[dict[str, Any]] = []
    for e in serp_search_log or []:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label") or "search")
        err = str(e.get("error") or "")
        ok = bool(e.get("ok"))
        if ok:
            status = "ok"
        elif "timed out" in err.lower() or "timeout" in err.lower():
            status = "timeout"
        elif e.get("empty") or (e.get("result_count") == 0):
            status = "empty"
        else:
            status = "fail"
        # Shorten long site: labels for UI
        short = label
        if "site:alibaba" in label.lower():
            short = "alibaba"
        elif "site:dhgat" in label.lower():
            short = "dhgate"
        elif "google_shopping" in label.lower() or label.startswith("primary:"):
            short = "google_shopping"
        elif "site:eu" in label.lower() or "europages" in label.lower():
            short = "europages"
        out.append(
            {
                "label": short,
                "raw_label": label,
                "status": status,
                "ok": ok,
                "error": err or None,
            }
        )
    return out
