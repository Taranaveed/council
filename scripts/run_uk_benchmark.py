"""
UK deal-finder benchmark runner (caching ON).

Modes:
  --data-only   No LLM. Market fetch + relevance + landed cost only.
  --full        Full deal-finder (LLM). Records model; FAILS if fallback model used.
  --record      With --data-only: save per-brief market JSON under benchmark/fixtures/market/
  --replay      Load market JSON from fixtures (no live SerpApi).
                Works with --data-only or --full (seeds market_client cache).

Examples:
  python scripts/run_uk_benchmark.py --data-only --record --limit 3
  python scripts/run_uk_benchmark.py --data-only --replay
  python scripts/run_uk_benchmark.py --full --replay --queries "earphones,notebooks"
  python scripts/run_uk_benchmark.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

_env = BACKEND / ".env"
if _env.is_file():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

DEFAULT_CSV = ROOT / "benchmark" / "uk_queries.csv"
REPORT_DIR = ROOT / "benchmark" / "reports"
FIXTURE_DIR = ROOT / "benchmark" / "fixtures" / "market"

# Observed bulk UK path: 1 primary google_shopping + 3 wholesale site searches
SERPAPI_PER_BRIEF_ESTIMATE = 4


class _CaptureStream(io.TextIOBase):
    def __init__(self, underlying: Any):
        self._u = underlying
        self.chunks: list[str] = []

    def write(self, s: str) -> int:  # type: ignore[override]
        self.chunks.append(s)
        return self._u.write(s)

    def flush(self) -> None:
        self._u.flush()

    def text(self) -> str:
        return "".join(self.chunks)


def _auth_headers(client) -> dict[str, str]:
    email = f"bench_{uuid.uuid4().hex[:10]}@example.com"
    password = "BenchPass123!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    if r.status_code >= 400:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _location(row: dict[str, str]) -> str:
    city = row.get("city") or "London"
    return f"{city}, United Kingdom"


def fixture_slug(query: str, *, gl: str, mode: str, currency: str) -> str:
    q = re.sub(r"[^a-z0-9]+", "_", (query or "").lower()).strip("_")[:60]
    return f"{q}__{gl.lower()}__{mode.lower()}__{currency.upper()}"


def fixture_path(query: str, *, gl: str, mode: str, currency: str) -> Path:
    return FIXTURE_DIR / f"{fixture_slug(query, gl=gl, mode=mode, currency=currency)}.json"


def save_market_fixture(
    *,
    row: dict[str, str],
    gl: str,
    mode: str,
    currency: str,
    listings: list[dict[str, Any]],
    listings_raw: list[dict[str, Any]],
    warning: str | None,
    searches_used: int,
    cache_key: str | None,
) -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = fixture_path(row["query"], gl=gl, mode=mode, currency=currency)
    payload = {
        "recorded_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "query": row["query"],
        "query_id": row.get("query_id"),
        "gl": gl,
        "mode": mode,
        "currency": currency,
        "city": row.get("city"),
        "quantity_note": (
            "Order qty is NOT part of the market fetch/cache; apply MOQ/tiers "
            "after loading this fixture."
        ),
        "cache_key": cache_key,
        "serpapi_searches": searches_used,
        "warning": warning,
        "listings": listings,
        "listings_raw": listings_raw,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_market_fixture(query: str, *, gl: str, mode: str, currency: str) -> dict[str, Any]:
    path = fixture_path(query, gl=gl, mode=mode, currency=currency)
    if not path.is_file():
        raise FileNotFoundError(f"Missing market fixture for replay: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_empty_fixture(
    query: str,
    *,
    gl: str = "uk",
    mode: str = "bulk",
    currency: str = "GBP",
    query_id: str | None = None,
    city: str | None = None,
) -> Path:
    """Create a recorded empty market fixture (nonsense / no-hit control)."""
    path = fixture_path(query, gl=gl, mode=mode, currency=currency)
    if path.is_file():
        return path
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    from app.core.market_client import market_cache_key

    payload = {
        "recorded_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "query": query,
        "query_id": query_id,
        "gl": gl,
        "mode": mode,
        "currency": currency,
        "city": city,
        "quantity_note": (
            "Synthetic empty fixture for nonsense/no-hit control — no live SerpApi."
        ),
        "cache_key": market_cache_key(
            query,
            country_code=gl,
            preferred_currency=currency,
            bulk_mode=(mode == "bulk"),
        ),
        "serpapi_searches": 0,
        "warning": "SerpApi returned zero usable seller prices for this query (gl=uk)",
        "listings": [],
        "listings_raw": [],
        "synthetic_empty": True,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _seed_listings_from_fixture(fix: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Prefer kept listings; if market-service kept none, surface priced Google
    Shopping / UK retail rows from listings_raw so --full --replay matches the
    data-only UK-merge path.
    """
    listings = [dict(x) for x in (fix.get("listings") or [])]
    if listings:
        return listings
    raw = [dict(x) for x in (fix.get("listings_raw") or [])]
    priced: list[dict[str, Any]] = []
    for x in raw:
        ep = x.get("extracted_price")
        try:
            ok = ep is not None and float(ep) > 0
        except (TypeError, ValueError):
            ok = False
        if ok or x.get("price"):
            priced.append(x)
    return priced[:16]


def seed_fixture_into_market_cache(row: dict[str, str]) -> str:
    """Load fixture JSON and seed market_client TTL cache for --full --replay."""
    from app.core.market_client import seed_market_cache

    qty = int(row.get("quantity") or 100)
    mode = (row.get("buying_mode") or "bulk").strip().lower()
    is_bulk = mode == "bulk" or qty >= 5
    buying_mode = "bulk" if is_bulk else "retail"
    currency = (row.get("currency") or "GBP").upper()
    gl = "uk"
    fix = load_market_fixture(
        row["query"], gl=gl, mode=buying_mode, currency=currency
    )
    seed_listings = _seed_listings_from_fixture(fix)
    key = seed_market_cache(
        product_name=row["query"],
        country_code=gl,
        preferred_currency=currency,
        bulk_mode=is_bulk,
        location=_location(row),
        listings=seed_listings,
        warning=fix.get("warning"),
        listings_raw=list(fix.get("listings_raw") or []),
    )
    # Also seed fixture cache_key if it differs (legacy key string).
    ck = fix.get("cache_key")
    if ck and ck != key:
        from app.core import market_client as mc

        mc._market_cache[ck] = mc._market_cache[key]
    return key


async def run_data_only(
    row: dict[str, str],
    *,
    record: bool = False,
    replay: bool = False,
    max_searches: int | None = None,
) -> dict[str, Any]:
    """Market + relevance + landed — no LLM / Groq."""
    from app.core.market_client import fetch_market_prices, get_last_market_fetch_meta
    from app.utils.landed_cost import compute_landed_cost
    from app.utils.relevance import filter_relevant_priced_listings
    from app.utils.spec_check import annotate_listings_with_spec_check
    from app.utils.gated_retail import merge_gated_warning
    from app.utils.supplier_table import attach_limited_data_landed
    from app.utils.uk_shopping_seller import (
        get_unrecognized_merchants,
        reset_unrecognized_merchants,
        uk_review_row_dump,
    )

    qty = int(row.get("quantity") or 100)
    mode = (row.get("buying_mode") or "bulk").strip().lower()
    is_bulk = mode == "bulk" or qty >= 5
    buying_mode = "bulk" if is_bulk else "retail"
    currency = (row.get("currency") or "GBP").upper()
    location = _location(row)
    gl = "uk"

    t0 = time.perf_counter()
    listings_raw: list[dict[str, Any]] = []
    cache_key = None
    serp_stats = {"attempts": 0, "retries": 0, "successes": 0, "failures": 0}
    serp_search_log: list[dict[str, Any]] = []
    reset_unrecognized_merchants()
    if replay:
        fix = load_market_fixture(
            row["query"], gl=gl, mode=buying_mode, currency=currency
        )
        listings = list(fix.get("listings") or [])
        listings_raw = list(fix.get("listings_raw") or [])
        warn = fix.get("warning")
        searches_used = 0
        from_cache = False
        cache_key = fix.get("cache_key")
        serp_search_log = []
    else:
        listings, warn = await fetch_market_prices(
            row["query"],
            location,
            country_code=gl,
            preferred_currency=currency,
            bulk_mode=is_bulk,
            quantity=qty,  # ignored by client for Serp fetch; kept for API compat
            use_cache=True,
        )
        fetch_meta = get_last_market_fetch_meta()
        searches_used = int(fetch_meta.get("serpapi_searches") or 0)
        serp_stats = dict(fetch_meta.get("serpapi_stats") or serp_stats)
        from_cache = bool(fetch_meta.get("from_cache"))
        listings_raw = list(fetch_meta.get("listings_raw") or [])
        cache_key = fetch_meta.get("cache_key")
        serp_search_log = list(fetch_meta.get("serpapi_search_log") or [])

    # Soft-rewrite legacy market warnings from old fixtures / copy
    if warn and "limited local supply" in str(warn).lower():
        warn = str(warn).replace(
            "limited local supply", "no priced UK listings found"
        ).replace(
            "Limited local supply", "No priced UK listings found"
        )

    if max_searches is not None and searches_used > max_searches:
        raise RuntimeError(
            f"Brief {row.get('query_id')!r} '{row.get('query')}' used "
            f"{searches_used} SerpApi searches (max {max_searches})"
        )

    if record and not replay:
        path = save_market_fixture(
            row=row,
            gl=gl,
            mode=buying_mode,
            currency=currency,
            listings=listings,
            listings_raw=listings_raw,
            warning=warn,
            searches_used=searches_used,
            cache_key=cache_key,
        )
        print(f"  recorded {path.name} (raw={len(listings_raw)} kept={len(listings)})")

    from app.utils.market_listings_prep import (
        prepare_market_listings,
        rewrite_market_warning_for_priced,
        source_status_from_serp_log,
    )

    listings = prepare_market_listings(
        listings,
        listings_raw,
        query=row["query"],
        location=location,
        country_code=gl,
        local_currency=currency,
        is_bulk=is_bulk,
    )

    listings, _ = annotate_listings_with_spec_check(listings, row["query"])
    kept, dropped, rel_meta = filter_relevant_priced_listings(
        listings, row["query"], is_bulk=is_bulk
    )
    uk_review = [
        x
        for x in listings
        if x.get("is_uk_shopping_seller")
        or x.get("price_review_only")
        or x.get("uk_retail_priced")
        or (
            str(x.get("host") or "") == "google.com"
            and (x.get("merchant") or x.get("is_shopping_offer"))
        )
    ]
    # Dedupe by link
    _seen_uk: set[str] = set()
    _uk_deduped = []
    for x in uk_review:
        k = str(x.get("link") or x.get("title") or id(x))
        if k in _seen_uk:
            continue
        _seen_uk.add(k)
        _uk_deduped.append(x)
    uk_review = _uk_deduped
    uk_review_rows = [uk_review_row_dump(x) for x in uk_review]
    uk_usable_price_n = sum(
        1 for x in uk_review_rows if x.get("usable_extracted_price") is not None
    )

    buyer_vat_reg = str(row.get("buyer_vat_registered") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )

    def _fmt_landed_note(mid: Any) -> str | None:
        if mid is None:
            return None
        s = str(mid).strip()
        return s if s else None

    def _landed_for_item(item: dict[str, Any]) -> dict[str, Any] | None:
        """
        Origin-aware landed (one primary number + assumption):
          confirmed_UK -> domestic (duty 0, import VAT 0, domestic VAT 20% line)
          likely_UK / unknown retail -> import figure + "if seller is UK-based: £X"
        """
        work = dict(item)
        work["_benchmark_query"] = row["query"]
        oc = str(work.get("uk_origin_class") or "")
        price_type = str(work.get("price_type") or "unknown")

        def _domestic_lc(w: dict[str, Any]) -> dict[str, Any] | None:
            return compute_landed_cost(
                {**w, "origin_country": "UK", "is_local": True},
                quantity=qty,
                local_currency=currency,
                location=location,
                country_code=gl,
                origin_country="UK",
                buyer_vat_registered=buyer_vat_reg,
            )

        def _import_lc(w: dict[str, Any]) -> dict[str, Any] | None:
            oc_country = w.get("origin_country") or "CN"
            if str(oc_country).upper() in ("UK", "GB"):
                oc_country = "CN"
            return compute_landed_cost(
                {**w, "origin_country": oc_country, "is_local": False},
                quantity=qty,
                local_currency=currency,
                location=location,
                country_code=gl,
                origin_country=str(oc_country),
                buyer_vat_registered=buyer_vat_reg,
            )

        if oc == "confirmed_UK":
            work["origin_country"] = "UK"
            work["is_local"] = True
            lc = _domestic_lc(work)
            if isinstance(lc, dict):
                lc["uk_origin_class"] = oc
                lc["verify_seller_origin"] = False
                vat_bit = (
                    "domestic VAT 20% reclaimable (excluded from mid; buyer_vat_registered)"
                    if buyer_vat_reg
                    else "domestic VAT 20% included in mid"
                )
                lc["landed_assumption"] = (
                    f"confirmed_UK domestic path: duty 0, import VAT 0, {vat_bit}"
                )
                lc["if_seller_uk_based"] = None
                lc["price_type"] = price_type
            return lc

        # likely_UK / unknown / sells_to_UK_only retail comps: primary = import
        if work.get("uk_retail_priced") or oc in (
            "likely_UK",
            "unknown",
            "sells_to_UK_only",
        ):
            as_uk = _domestic_lc(work)
            as_imp = _import_lc(work)
            primary = dict(as_imp or {}) if isinstance(as_imp, dict) else {}
            uk_mid = (as_uk or {}).get("estimated_total") if isinstance(as_uk, dict) else None
            # If import hidden but UK path visible, still prefer import figure when present
            primary["uk_origin_class"] = oc or "unknown"
            primary["verify_seller_origin"] = True
            primary["landed_as_uk"] = as_uk
            primary["landed_as_import"] = as_imp
            primary["landed_as_uk_mid"] = uk_mid
            primary["landed_as_import_mid"] = (
                (as_imp or {}).get("estimated_total") if isinstance(as_imp, dict) else None
            )
            primary["if_seller_uk_based"] = _fmt_landed_note(uk_mid)
            primary["landed_note"] = (
                f"if seller is UK-based: {uk_mid}" if uk_mid is not None else None
            )
            primary["landed_assumption"] = (
                "import path (duty + freight + import VAT); "
                + (f"if seller is UK-based: {uk_mid}" if uk_mid is not None else "verify seller origin")
            )
            primary["price_type"] = price_type
            # Keep import estimated_total as the ONE primary number
            if isinstance(as_imp, dict) and as_imp.get("estimated_total") is not None:
                primary["estimated_total"] = as_imp.get("estimated_total")
                primary["hide_landed"] = bool(as_imp.get("hide_landed"))
            return primary or as_imp

        lc = compute_landed_cost(
            work,
            quantity=qty,
            local_currency=currency,
            location=location,
            country_code=gl,
            buyer_vat_registered=buyer_vat_reg,
        )
        if isinstance(lc, dict):
            lc["price_type"] = price_type
            lc["landed_assumption"] = (
                "import path" if lc.get("is_import") else "domestic path"
            )
        return lc

    display = kept if kept else []
    # NO_MATCH + implausible: do not invent landed from penny rows
    plausible_kept = [
        x
        for x in (kept or [])
        if not (
            x.get("price_outlier")
            or x.get("price_implausible")
            or x.get("unit_price_unreliable")
        )
    ]
    if kept and len(kept) < 2:
        # Still run landed guards — hide absurd single-row NO_MATCH pennies/lot prices
        display = []
        for item in kept:
            landed = _landed_for_item(item)
            row_out = dict(item)
            row_out["landed_cost"] = landed
            if isinstance(landed, dict) and (
                landed.get("hide_landed")
                or landed.get("price_flagged")
                or landed.get("needs_quote")
            ):
                row_out["price_flagged"] = True
                row_out["price_flag_reasons"] = landed.get("price_flag_reasons") or []
                row_out["needs_quote"] = bool(landed.get("needs_quote"))
            elif plausible_kept and item in plausible_kept:
                pass
            display.append(row_out)
        if (
            not any(x.get("price_flagged") for x in display)
            and plausible_kept
            and not any(x.get("uk_retail_priced") for x in display)
        ):
            display = attach_limited_data_landed(
                plausible_kept,
                quantity=qty,
                local_currency=currency,
                location=location,
                country_code=gl,
            )
    else:
        enriched = []
        for item in display:
            landed = _landed_for_item(item)
            row_out = dict(item)
            row_out["landed_cost"] = landed
            if isinstance(landed, dict) and (
                landed.get("hide_landed") or landed.get("price_flagged") or landed.get("needs_quote")
            ):
                row_out["price_flagged"] = True
                row_out["price_flag_reasons"] = landed.get("price_flag_reasons") or []
                row_out["needs_quote"] = bool(landed.get("needs_quote"))
            enriched.append(row_out)
        display = enriched
        priced_ok = [
            x
            for x in display
            if not x.get("price_flagged")
            and not (
                isinstance(x.get("landed_cost"), dict)
                and x["landed_cost"].get("hide_landed")
            )
        ]
        if len(priced_ok) < 2:
            rel_meta = dict(rel_meta)
            rel_meta["relevant_priced_count"] = len(priced_ok)
            rel_meta["no_good_matches"] = True
            rel_meta["flagged_after_landed"] = len(display) - len(priced_ok)

    uk_priced_in_display = sum(
        1
        for x in display
        if x.get("uk_retail_priced")
        and not x.get("price_flagged")
        and not (
            isinstance(x.get("landed_cost"), dict) and x["landed_cost"].get("hide_landed")
        )
    )
    # Fix stale "no priced UK listings found" when UK retail comps are present
    if warn and uk_priced_in_display > 0:
        warn = re.sub(
            r"best available \(no priced UK listings found\)",
            f"{uk_priced_in_display} UK retail price(s) in comparison (verify bulk; never Best)",
            str(warn),
            flags=re.I,
        )
        warn = re.sub(
            r"no priced UK listings found",
            f"{uk_priced_in_display} UK retail price(s) in comparison (verify bulk)",
            str(warn),
            flags=re.I,
        )

    warn = merge_gated_warning(warn, row["query"], len(listings))

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    # Local by host/origin — NOT currency_mismatch; skip flagged/hidden
    def _visible(x: dict) -> bool:
        lc = x.get("landed_cost") if isinstance(x.get("landed_cost"), dict) else {}
        return not x.get("price_flagged") and not (lc or {}).get("hide_landed")

    local_n = sum(
        1
        for x in display
        if _visible(x)
        and (
            x.get("is_local")
            or str(x.get("uk_origin_class") or "") == "confirmed_UK"
        )
    )
    import_n = sum(
        1
        for x in display
        if _visible(x)
        and not (
            x.get("is_local")
            or str(x.get("uk_origin_class") or "") == "confirmed_UK"
        )
    )
    landed_rows = []
    for x in display:
        lc = x.get("landed_cost") if isinstance(x.get("landed_cost"), dict) else None
        if lc:
            unit = lc.get("unit_price")
            goods = lc.get("goods_amount")
            qn = lc.get("quantity") or qty
            goods_ok = None
            try:
                from app.utils.money import parse_money

                u_amt = parse_money(str(unit or ""))
                if u_amt is not None and goods is not None and qn:
                    ul = parse_money(str(lc.get("unit_price_local") or ""))
                    if ul is not None:
                        goods_ok = abs(float(goods) - float(ul) * float(qn)) < 0.05 * max(
                            float(goods), 1.0
                        )
            except Exception:
                goods_ok = None
            loc_kind = (
                "local"
                if (
                    x.get("is_local")
                    or str(x.get("uk_origin_class") or "") == "confirmed_UK"
                )
                else "import"
            )
            landed_rows.append(
                {
                    "vendor": x.get("vendor") or x.get("merchant"),
                    "host": x.get("host"),
                    "link": x.get("link"),
                    "price": x.get("price"),
                    "extracted_price": x.get("extracted_price"),
                    "unit_price": unit,
                    "unit_price_local": lc.get("unit_price_local"),
                    "goods_amount": goods,
                    "goods_matches_unit_x_qty": goods_ok,
                    "quantity": qn,
                    "tier_label": lc.get("tier_label") or lc.get("price_tier_label"),
                    "moq": lc.get("moq"),
                    "moq_not_met": lc.get("moq_not_met"),
                    "landed_mid": None if lc.get("hide_landed") else lc.get("estimated_total"),
                    "hide_landed": bool(lc.get("hide_landed")),
                    "landed_goods_multiple": lc.get("landed_goods_multiple"),
                    "limited_data": bool(lc.get("limited_data")),
                    "origin": lc.get("origin_country") or x.get("origin_country"),
                    "is_local": bool(x.get("is_local"))
                    or str(x.get("uk_origin_class") or "") == "confirmed_UK",
                    "is_import": bool(lc.get("is_import")),
                    "local_or_import": loc_kind,
                    "uk_origin_class": x.get("uk_origin_class") or lc.get("uk_origin_class"),
                    "uk_origin_evidence": x.get("uk_origin_evidence") or [],
                    "verify_seller_origin": bool(lc.get("verify_seller_origin")),
                    "landed_assumption": lc.get("landed_assumption"),
                    "if_seller_uk_based": lc.get("if_seller_uk_based") or lc.get("landed_note"),
                    "landed_as_uk_mid": lc.get("landed_as_uk_mid"),
                    "landed_as_import_mid": lc.get("landed_as_import_mid"),
                    "uk_retail_priced": bool(x.get("uk_retail_priced")),
                    "price_type": x.get("price_type") or lc.get("price_type") or "unknown",
                    "branded_goods": bool(x.get("branded_goods")),
                    "branded_goods_note": x.get("branded_goods_note"),
                    "best_pick_eligible": False
                    if (x.get("uk_retail_priced") or x.get("price_type") == "retail")
                    else x.get("best_pick_eligible"),
                    "sourcing_note": x.get("sourcing_note")
                    or (
                        "single-unit retail price; confirm quantity limits and bulk discount"
                        if x.get("price_type") == "retail"
                        else x.get("uk_seller_label")
                    ),
                    "price_may_be_per_pack": lc.get("price_may_be_per_pack"),
                    "pack_text": lc.get("pack_text"),
                    "warning_freight_minimum": lc.get("warning_freight_minimum"),
                    "warning_implausible_price": lc.get("warning_implausible_price"),
                    "price_flagged": bool(
                        lc.get("price_flagged") or lc.get("hide_landed") or x.get("price_flagged")
                    ),
                    "price_flag_reasons": lc.get("price_flag_reasons")
                    or x.get("price_flag_reasons")
                    or [],
                    "needs_quote": bool(lc.get("needs_quote") or x.get("needs_quote")),
                    "guards": lc.get("guards") or [],
                    "price_soft_flagged": bool(lc.get("price_soft_flagged")),
                    "price_includes_vat": lc.get("price_includes_vat")
                    if lc.get("price_includes_vat") is not None
                    else (lc.get("landed_as_uk") or {}).get("price_includes_vat")
                    if isinstance(lc.get("landed_as_uk"), dict)
                    else None,
                    "vat_basis": lc.get("vat_basis")
                    or (
                        (lc.get("landed_as_uk") or {}).get("vat_basis")
                        if isinstance(lc.get("landed_as_uk"), dict)
                        else None
                    ),
                    "vat_basis_unknown": bool(
                        lc.get("vat_basis_unknown")
                        if "vat_basis_unknown" in lc
                        else (lc.get("landed_as_uk") or {}).get("vat_basis_unknown")
                        if isinstance(lc.get("landed_as_uk"), dict)
                        else True
                    ),
                    "vat_basis_note": lc.get("vat_basis_note")
                    or (
                        (lc.get("landed_as_uk") or {}).get("vat_basis_note")
                        if isinstance(lc.get("landed_as_uk"), dict)
                        else None
                    ),
                    "goods_shelf_amount": lc.get("goods_shelf_amount")
                    or (
                        (lc.get("landed_as_uk") or {}).get("goods_shelf_amount")
                        if isinstance(lc.get("landed_as_uk"), dict)
                        else None
                    ),
                }
            )

    no_match = bool(rel_meta.get("no_good_matches"))
    kept_priced_n = int(rel_meta.get("relevant_priced_count") or len(kept))
    if any(x.get("price_flagged") for x in display):
        kept_priced_n = sum(
            1
            for x in display
            if not x.get("price_flagged")
            and not (
                isinstance(x.get("landed_cost"), dict) and x["landed_cost"].get("hide_landed")
            )
        )
    # Cache-hit instrumentation (client TTL + per-SerpApi call log when live)
    cache_hits = sum(
        1 for s in serp_search_log if s.get("cache_hit") is True
    )
    cache_misses = sum(
        1 for s in serp_search_log if s.get("cache_hit") is False
    )
    cache_unknown = sum(
        1 for s in serp_search_log if s.get("cache_hit") is None
    )
    serp_stats = {
        **serp_stats,
        "cache_hits": cache_hits if not from_cache else max(cache_hits, 1),
        "cache_misses": cache_misses,
        "cache_unknown": cache_unknown,
        "client_from_cache": from_cache,
        "replay_fixture": bool(replay),
    }
    return {
        "mode": "data-only",
        "query_id": row.get("query_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "quantity": qty,
        "buying_mode": mode,
        "city": row.get("city"),
        "elapsed_ms": elapsed_ms,
        "listing_count_raw": len(listings_raw) if listings_raw else len(listings),
        "listing_count_kept_fetch": len(listings),
        "kept_priced": kept_priced_n,
        "uk_retail_priced_count": uk_priced_in_display,
        "dropped": len(dropped),
        "uk_seller_review_count": len(uk_review),
        "uk_review_usable_extracted_price_count": uk_usable_price_n,
        "uk_review_rows": uk_review_rows,
        "priced_rate": (kept_priced_n / len(listings)) if listings else 0.0,
        "local_count": local_n,
        "import_count": import_n,
        "no_match": no_match,
        "landed_rows": landed_rows,
        "market_warning": (
            rewrite_market_warning_for_priced(
                warn,
                priced_count=max(kept_priced_n, uk_priced_in_display, uk_usable_price_n),
                source_status=source_status_from_serp_log(serp_search_log),
            )
            or ""
        )[:500],
        "serp_source_status": source_status_from_serp_log(serp_search_log),
        "relevance": rel_meta,
        "searches_used": searches_used,
        "serpapi_stats": serp_stats,
        "serpapi_search_log": serp_search_log,
        "from_cache": from_cache,
        "cache_key": cache_key,
        "replay": replay,
        "recorded": record and not replay,
        "listings_raw_count": len(listings_raw),
        "uk_unrecognized_merchants": get_unrecognized_merchants(),
        "searches_estimate": SERPAPI_PER_BRIEF_ESTIMATE,
        "llm": False,
    }


def run_full(
    client,
    headers: dict[str, str],
    row: dict[str, str],
    *,
    replay: bool = False,
) -> dict[str, Any]:
    """Full deal-finder; fail if Groq fallback model was used."""
    primary = (os.getenv("GROQ_MODEL") or "").strip()
    fallback = (os.getenv("GROQ_FALLBACK_MODEL") or "").strip()

    cache_key = None
    if replay:
        cache_key = seed_fixture_into_market_cache(row)

    body = {
        "item_name": row["query"],
        "location": _location(row),
        "currency": row.get("currency") or "GBP",
        "quantity": int(row.get("quantity") or 100),
        "buying_mode": row.get("buying_mode") or "bulk",
        "marketplace": "local_retailers",
    }

    cap_out = _CaptureStream(sys.stdout)
    cap_err = _CaptureStream(sys.stderr)
    old_out, old_err = sys.stdout, sys.stderr
    t0 = time.perf_counter()
    try:
        sys.stdout, sys.stderr = cap_out, cap_err
        r = client.post("/api/modes/deal-finder", headers=headers, json=body)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    log_blob = cap_out.text() + "\n" + cap_err.text()

    fallback_used = bool(
        re.search(r"falling back to\s+(\S+)", log_blob, re.I)
        or (fallback and re.search(re.escape(fallback), log_blob) and "falling back" in log_blob.lower())
    )
    model_match = re.findall(r"falling back to\s+(\S+)", log_blob, re.I)
    model_used = model_match[-1].rstrip(":") if model_match else (primary or "unknown")
    if fallback_used:
        raise RuntimeError(
            f"FULL mode refused mixed models for query_id={row.get('query_id')!r}: "
            f"fallback model was used ({model_used}). Primary={primary!r} fallback={fallback!r}. "
            f"Re-run when primary quota recovers, or set GROQ_MODEL to the only model you accept."
        )

    out: dict[str, Any] = {
        "mode": "full",
        "query_id": row.get("query_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "quantity": body["quantity"],
        "buying_mode": body["buying_mode"],
        "city": row.get("city"),
        "http_status": r.status_code,
        "elapsed_ms": elapsed_ms,
        "model_primary_env": primary,
        "model_used": model_used,
        "fallback_used": False,
        "searches_estimate": SERPAPI_PER_BRIEF_ESTIMATE if not replay else 0,
        "searches_used": 0 if replay else None,
        "replay": bool(replay),
        "cache_key": cache_key,
        "llm": True,
        # Manual-review columns (filled after response)
        "winner_title": None,
        "winner_vendor": None,
        "winner_reason": None,
        "winner_landed": None,
        "flags": [],
    }
    if r.status_code != 200:
        out["error"] = r.text[:800]
        return out
    data = r.json()
    verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else {}
    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    listings = data.get("market_listings") or []
    flag_bits: list[str] = []
    if data.get("market_warning"):
        flag_bits.append("market_warning")
    if verdict.get("verdict") == "NO_MATCH":
        flag_bits.append("NO_MATCH")
    landed_mids: list[float] = []
    for x in listings:
        if not isinstance(x, dict):
            continue
        lc = x.get("landed_cost") if isinstance(x.get("landed_cost"), dict) else {}
        if lc.get("hide_landed"):
            flag_bits.append("hide_landed")
        if lc.get("price_soft_flagged"):
            flag_bits.append("soft_3x")
        if lc.get("limited_data"):
            flag_bits.append("limited_data")
        if x.get("uk_retail_priced"):
            flag_bits.append("uk_retail")
        mid = lc.get("estimated_total")
        try:
            if mid is not None:
                landed_mids.append(float(mid))
        except (TypeError, ValueError):
            pass
    w_landed = None
    if isinstance(winner, dict):
        wlc = winner.get("landed_cost")
        if isinstance(wlc, dict):
            w_landed = wlc.get("estimated_total")
        elif winner.get("landed") is not None:
            w_landed = winner.get("landed")
        elif winner.get("estimated_total") is not None:
            w_landed = winner.get("estimated_total")
    out.update(
        {
            "verdict": verdict.get("verdict"),
            "winner_title": (winner.get("title") or "")[:80] or None,
            "winner_vendor": winner.get("vendor") or winner.get("merchant"),
            "winner_reason": (winner.get("reason") or verdict.get("summary") or "")[:200]
            or None,
            "winner_landed": w_landed,
            "flags": list(dict.fromkeys(flag_bits)),
            "listing_count": len(listings),
            "landed_rows": sum(
                1 for x in listings if isinstance(x, dict) and isinstance(x.get("landed_cost"), dict)
            ),
            "landed_mid_min": min(landed_mids) if landed_mids else None,
            "landed_mid_max": max(landed_mids) if landed_mids else None,
            "limited_data_rows": sum(
                1
                for x in listings
                if isinstance(x, dict)
                and isinstance(x.get("landed_cost"), dict)
                and x["landed_cost"].get("limited_data")
            ),
            "market_warning": str(data.get("market_warning") or "")[:500],
            "relevance": (data.get("query_meta") or {}).get("relevance")
            if isinstance(data.get("query_meta"), dict)
            else None,
        }
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UK deal-finder benchmark")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=0, help="Max rows (0 = all)")
    parser.add_argument(
        "--queries",
        type=str,
        default="",
        help="Comma-separated exact query strings to run (dedupe by query)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Save per-brief market JSON (listings + listings_raw) under fixtures/market",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Load market JSON from fixtures (no live SerpApi)",
    )
    parser.add_argument(
        "--max-searches",
        type=int,
        default=0,
        help="Fail a brief if SerpApi searches exceed this (0 = no per-brief cap)",
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--data-only",
        action="store_true",
        help="No LLM: market + relevance + landed only",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="Full deal-finder; fail if Groq fallback model used",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not args.data_only and not args.full:
        parser.error("Specify --data-only or --full (or --dry-run)")
    if args.record and args.replay:
        parser.error("Use --record or --replay, not both")
    if args.record and args.full:
        parser.error("--record only supported with --data-only")

    if not args.csv.is_file():
        print(f"Missing CSV: {args.csv}", file=sys.stderr)
        return 1

    rows: list[dict[str, str]] = []
    with args.csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("query"):
                rows.append(row)

    if args.queries.strip():
        wanted = [q.strip() for q in args.queries.split(",") if q.strip()]
        by_q: dict[str, dict[str, str]] = {}
        for row in rows:
            q = row["query"]
            if q in wanted and q not in by_q:
                by_q[q] = row
        missing = [q for q in wanted if q not in by_q]
        if missing:
            print(f"Queries not in CSV: {missing}", file=sys.stderr)
            return 1
        rows = [by_q[q] for q in wanted]

    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    print(f"Loaded {len(rows)} queries from {args.csv}")
    print(f"Per-brief SerpApi estimate (current bulk path): {SERPAPI_PER_BRIEF_ESTIMATE}")
    if args.replay:
        print("REPLAY mode — no live SerpApi calls (fixtures only)")
        print("Estimated total SerpApi for this run: 0")
    else:
        print(f"Estimated total SerpApi for this run: {SERPAPI_PER_BRIEF_ESTIMATE * len(rows)}")
    if args.record:
        print(f"RECORD mode — fixtures → {FIXTURE_DIR}")
    if args.dry_run:
        for r in rows:
            print(
                f"  [{r.get('query_id')}] {r.get('category')}: {r.get('query')!r} "
                f"qty={r.get('quantity')} mode={r.get('buying_mode')}"
            )
        print("Dry run only — not calling APIs.")
        return 0

    if args.replay:
        # Ensure nonsense / missing empty controls exist without live SerpApi.
        for row in rows:
            if (row.get("category") or "").strip().lower() == "nonsense":
                ensure_empty_fixture(
                    row["query"],
                    query_id=row.get("query_id"),
                    city=row.get("city"),
                )
        from app.core.market_client import clear_market_cache, set_fixture_replay

        clear_market_cache()
        set_fixture_replay(True, ttl_sec=86400.0)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = "data" if args.data_only else "full"
    if args.replay:
        tag += "_replay"
    elif args.record:
        tag += "_record"
    report_path = REPORT_DIR / f"uk_benchmark_{tag}_{stamp}.json"

    results: list[dict[str, Any]] = []
    early_stop: str | None = None
    max_searches = args.max_searches if args.max_searches > 0 else None

    if args.data_only:
        import asyncio

        for i, row in enumerate(rows, 1):
            print(f"[data-only {i}/{len(rows)}] {row.get('query')} …")
            try:
                results.append(
                    asyncio.run(
                        run_data_only(
                            row,
                            record=args.record,
                            replay=args.replay,
                            max_searches=max_searches,
                        )
                    )
                )
            except RuntimeError as e:
                early_stop = str(e)
                print(f"EARLY STOP: {early_stop}")
                break
            except FileNotFoundError as e:
                early_stop = str(e)
                print(f"EARLY STOP: {early_stop}")
                break
            # Legacy gate: first 5 all >6 searches OR all NO_MATCH
            if i == 5 and not args.replay:
                first5 = results[:5]
                searches = [int(r.get("searches_used") or 0) for r in first5]
                no_matches = [bool(r.get("no_match")) for r in first5]
                if all(s > 6 for s in searches):
                    early_stop = (
                        f"first 5 briefs each used >6 SerpApi searches "
                        f"({searches}); stopping to protect quota"
                    )
                elif all(no_matches):
                    early_stop = "first 5 briefs all NO_MATCH; stopping"
                if early_stop:
                    print(f"EARLY STOP: {early_stop}")
                    break
    else:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        headers = _auth_headers(client)
        for i, row in enumerate(rows, 1):
            print(f"[full {i}/{len(rows)}] {row.get('query')} …")
            try:
                results.append(run_full(client, headers, row, replay=args.replay))
            except RuntimeError as e:
                early_stop = str(e)
                print(f"EARLY STOP: {early_stop}")
                break
            except FileNotFoundError as e:
                early_stop = str(e)
                print(f"EARLY STOP: {early_stop}")
                break

    payload = {
        "generated_at": stamp,
        "mode": "data-only" if args.data_only else "full",
        "record": bool(args.record),
        "replay": bool(args.replay),
        "csv": str(args.csv.as_posix()),
        "count": len(results),
        "early_stop": early_stop,
        "serpapi_per_brief_estimate": SERPAPI_PER_BRIEF_ESTIMATE,
        "serpapi_total_estimate": SERPAPI_PER_BRIEF_ESTIMATE * len(results),
        "serpapi_searches_used_sum": sum(int(r.get("searches_used") or 0) for r in results),
        "market_cache_ttl_sec": float(os.getenv("MARKET_CACHE_TTL_SEC", "90")),
        "cache_key_note": (
            "key = query|gl|mode|currency; qty/city excluded; "
            "MOQ/tier selection applied post-cache in landed_cost"
        ),
        "results": results,
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {report_path}")
    if early_stop:
        print(f"Stopped early: {early_stop}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
