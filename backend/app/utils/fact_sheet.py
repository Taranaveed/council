"""Structured fact sheet from live listings — agents may only cite these numbers."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.utils.money import parse_money


def _valid_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        p = urlparse(text)
    except Exception:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    return text


def _is_product_url(link: str) -> bool:
    u = (link or "").lower()
    if not u:
        return False
    return bool(re.search(r"/product-detail/|/products?/|/proddetail|/item/|/itm/|/dp/", u))


def _add_number(bucket: set[float], raw: Any) -> None:
    n = parse_money(raw)
    if n is not None and n > 0:
        bucket.add(round(n, 4))
        # Also allow integer form of money amounts
        bucket.add(float(round(n)))


def build_listing_fact_sheet(listings: list[dict[str, Any]]) -> dict[str, Any]:
    """
    One row per listing with sourced fields. Unit prices from storefronts
    or missing extracts are marked rejected / missing — not usable as facts.
    """
    rows: list[dict[str, Any]] = []
    numbers: set[float] = set()

    for item in listings or []:
        link = _valid_url(item.get("link"))
        product = bool(item.get("is_product_page")) if "is_product_page" in item else _is_product_url(link)
        price_raw = str(item.get("price") or "").strip()
        price_source = str(item.get("price_source") or "serp").lower()
        rejected = (
            not product
            or price_source in ("rejected_storefront",)
            or bool(item.get("unit_price_rejected"))
            or bool(re.match(r"^(see listing|n/?a)$", price_raw, re.I))
        )

        unit_amt = None if rejected else parse_money(price_raw)
        if unit_amt is None and not rejected:
            rejected = True  # missing from extracted data

        verified = (
            not rejected
            and price_source in ("page", "tier", "page_scalar")
            and bool(item.get("unit_price_verified", True))
        )

        moq = item.get("moq")
        moq_src = str(item.get("moq_source") or "").lower()
        try:
            moq_n = int(moq) if moq is not None and str(moq).strip() != "" else None
        except (TypeError, ValueError):
            moq_n = None
        if (
            moq_src in ("not_on_snippet", "not_verified", "assumed_1_from_page_price", "missing", "")
            or moq_src.startswith("not_")
        ):
            moq_n = None

        tiers_out: list[dict[str, Any]] = []
        for t in item.get("price_tiers") or []:
            if not isinstance(t, dict):
                continue
            t_amt = parse_money(t.get("unit_price") or t.get("price"))
            if t_amt is None:
                continue
            entry = {
                "min_qty": t.get("min_qty"),
                "max_qty": t.get("max_qty"),
                "unit_price": t.get("unit_price"),
                "currency": t.get("currency"),
                "source": t.get("source") or item.get("tiers_source") or "extracted",
            }
            tiers_out.append(entry)
            _add_number(numbers, t_amt)
            if t.get("min_qty") is not None:
                try:
                    numbers.add(float(int(t["min_qty"])))
                except (TypeError, ValueError):
                    pass

        weight_kg = item.get("package_weight_kg")
        weight_src = str(item.get("package_weight_source") or "").lower()
        try:
            weight_f = float(weight_kg) if weight_kg is not None else None
        except (TypeError, ValueError):
            weight_f = None
        if weight_src not in ("page", "page_facts", "html"):
            weight_f = None

        if unit_amt is not None and verified:
            _add_number(numbers, unit_amt)
        if moq_n is not None:
            numbers.add(float(moq_n))
        if weight_f is not None and weight_f > 0:
            numbers.add(round(weight_f, 4))

        row = {
            "title": str(item.get("title") or "")[:120],
            "vendor": str(item.get("vendor") or item.get("source") or ""),
            "link": link,
            "is_product_page": product,
            "unit_price": None if rejected else price_raw,
            "unit_price_amount": unit_amt if not rejected else None,
            "unit_price_source": price_source,
            "unit_price_verified": verified,
            "unit_price_status": (
                "rejected_storefront"
                if not product or price_source == "rejected_storefront"
                else "missing"
                if unit_amt is None
                else "verified"
                if verified
                else "unverified_serp"
            ),
            "moq": moq_n,
            "moq_source": (item.get("moq_source") if moq_n is not None else "not_confirmed"),
            "price_tiers": tiers_out,
            "tiers_source": item.get("tiers_source"),
            "package_weight_kg": weight_f,
            "package_weight_raw": item.get("package_weight_raw") if weight_f is not None else None,
            "package_weight_source": (
                item.get("package_weight_source") if weight_f is not None else "not_confirmed"
            ),
            "page_facts_fetched": bool(item.get("page_facts_fetched")),
            "warranty": item.get("warranty"),
            "warranty_source": item.get("warranty_source"),
            "policy_links": item.get("policy_links") if isinstance(item.get("policy_links"), list) else [],
            "variants": item.get("variants") if isinstance(item.get("variants"), list) else [],
            "channel": item.get("channel"),
            "sourcing_action": item.get("sourcing_action"),
            "spec_misses": item.get("spec_misses") if isinstance(item.get("spec_misses"), list) else [],
            "currency": item.get("currency"),
            "best_pick": bool(item.get("best_pick")),
        }
        rows.append(row)

    return {
        "listings": rows,
        "allowed_numbers": sorted(numbers),
        "note": (
            "Agents may only cite numbers that appear in this fact sheet "
            "(unit prices, MOQ, tier mins, package weight). "
            "Storefront and missing unit prices are rejected."
        ),
    }


def fact_sheet_for_prompt(sheet: dict[str, Any] | None) -> str:
    if not sheet or not isinstance(sheet, dict):
        return ""
    lines = ["FACT SHEET (cite only these numbers):"]
    for i, row in enumerate(sheet.get("listings") or [], 1):
        if not isinstance(row, dict):
            continue
        status = row.get("unit_price_status")
        price_bit = (
            f"unit={row.get('unit_price')} [{row.get('unit_price_source')}/{status}]"
            if row.get("unit_price")
            else f"unit=REJECTED({status})"
        )
        moq_bit = (
            f"MOQ={row.get('moq')} (source={row.get('moq_source')})"
            if row.get("moq") is not None
            else "MOQ=not_confirmed — verify on seller page"
        )
        wt = row.get("package_weight_kg")
        wt_bit = (
            f"weight_kg={wt} (page)"
            if wt and str(row.get("package_weight_source") or "") in ("page", "page_facts", "html")
            else "weight_kg=not_confirmed"
        )
        tiers = row.get("price_tiers") or []
        tier_bit = ""
        if tiers:
            bits = [f"{t.get('min_qty')}+@{t.get('unit_price')}" for t in tiers[:5] if isinstance(t, dict)]
            if bits:
                tier_bit = f" | tiers=[{', '.join(bits)}]"
        lines.append(
            f"{i}. {row.get('title')} | {price_bit} | {moq_bit} | {wt_bit}{tier_bit} | {row.get('link')}"
        )
    lines.append(str(sheet.get("note") or ""))
    return "\n".join(lines)


_CITED_NUMBER_RE = re.compile(
    r"(?:Rs\.?\s*|PKR\s*|USD\s*|\$|€|£|₹)?\s*([\d]{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)",
    re.I,
)

# Skip year-like / tiny structural numbers in cite check
_SKIP_CTX = re.compile(
    r"(?:19|20)\d{2}|^\d$",
)


def extract_cited_amounts(text: str) -> list[float]:
    """Only money-like citations (currency nearby or amounts ≥ 10)."""
    found: list[float] = []
    blob = str(text or "")
    for m in _CITED_NUMBER_RE.finditer(blob):
        raw = m.group(1)
        span_start = max(0, m.start() - 12)
        nearby = blob[span_start : m.end() + 6]
        n = parse_money(raw)
        if n is None:
            continue
        if _SKIP_CTX.search(raw) and n >= 1900:
            continue
        has_currency = bool(re.search(r"Rs\.?|PKR|\$|USD|€|£|₹|AED|SAR", nearby, re.I))
        per_piece = bool(re.search(r"per\s+(?:piece|pc|unit)|/pc\b|@\s*$", nearby, re.I))
        # Skip small bare integers (counts, ranks) unless currency-tagged
        if not has_currency and not per_piece and n < 10:
            continue
        if not has_currency and n < 50 and "." not in raw and "," not in raw:
            # bare "25%" style — skip if % follows
            if re.match(r"\s*%", blob[m.end() : m.end() + 2]):
                continue
        found.append(n)
    return found


def cite_check_against_sheet(
    texts: list[str],
    sheet: dict[str, Any] | None,
    *,
    landed: dict[str, Any] | None = None,
    tol: float = 0.08,
) -> list[str]:
    """
    Return list of orphan amounts cited in agent/verdict prose that are not
    in the fact sheet (or in the landed-cost assumption numbers we publish).
    """
    allowed: set[float] = set()
    if sheet and isinstance(sheet, dict):
        for n in sheet.get("allowed_numbers") or []:
            try:
                allowed.add(float(n))
                allowed.add(float(round(float(n))))
            except (TypeError, ValueError):
                pass

    if landed and isinstance(landed, dict):
        for key in (
            "unit_price",
            "unit_price_local",
            "line_total",
            "duty_amount",
            "shipping_amount",
            "estimated_total",
            "range_low",
            "range_high",
            "freight_rate",
            "package_weight_kg",
            "moq",
            "quantity",
        ):
            v = landed.get(key)
            if isinstance(v, (int, float)):
                allowed.add(float(v))
                allowed.add(float(round(float(v))))
            else:
                n = parse_money(v)
                if n is not None:
                    allowed.add(n)
                    allowed.add(float(round(n)))
        # duty % as integer percent
        dr = landed.get("duty_rate")
        if isinstance(dr, (int, float)) and dr > 0:
            allowed.add(float(int(round(dr * 100))))
        for band in ("duty_rate_low", "duty_rate_high", "freight_rate_low", "freight_rate_high"):
            bv = landed.get(band)
            if isinstance(bv, (int, float)):
                allowed.add(float(bv))
                if band.startswith("duty") and bv <= 1:
                    allowed.add(float(int(round(bv * 100))))

    orphans: list[str] = []
    seen: set[float] = set()
    blob = "\n".join(str(t or "") for t in texts)
    for n in extract_cited_amounts(blob):
        key = round(n, 2)
        if key in seen:
            continue
        seen.add(key)
        ok = any(
            abs(n - a) / max(n, a, 1e-9) <= tol or abs(n - a) < 1.0
            for a in allowed
            if a > 0
        )
        if not ok and allowed:
            orphans.append(str(n if n != int(n) else int(n)))
    return orphans
