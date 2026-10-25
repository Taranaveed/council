"""Deterministic price explanation from live listings + seller band."""
from __future__ import annotations

import re
from typing import Any


def parse_money(value: Any) -> float | None:
    text = str(value or "")
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", text.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def listing_numbers(listings: list[dict[str, Any]], *, local_only: bool = False) -> list[float]:
    nums: list[float] = []
    for row in listings or []:
        if local_only and row.get("currency_mismatch"):
            continue
        n = parse_money(row.get("price"))
        if n is not None and n > 0:
            nums.append(n)
    return nums


def median(nums: list[float]) -> float | None:
    if not nums:
        return None
    s = sorted(nums)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def format_amount(n: float | None, currency: str) -> str:
    if n is None:
        return "—"
    cur = (currency or "").strip().upper() or ""
    if n >= 1000:
        body = f"{n:,.0f}"
    else:
        body = f"{n:,.2f}".rstrip("0").rstrip(".")
    return f"{cur} {body}".strip() if cur else body


def _pct_gap(a: float, b: float) -> float:
    """Absolute percent gap of a vs b (relative to b)."""
    if b == 0:
        return 0.0
    return abs(a - b) / abs(b) * 100.0


def _sort_key_price(row: dict[str, Any]) -> float:
    n = parse_money(row.get("price"))
    return n if n is not None and n > 0 else float("inf")


def prepare_seller_comps(
    listings: list[dict[str, Any]],
    *,
    query: str,
    currency: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Seller Fair Price / Launch comps: keep live product pages with real prices,
    prefer the seller's currency, then add a few reasonable foreign references.
    """
    from app.utils.listing_channel import annotate_listing_channels
    from app.utils.relevance import (
        filter_relevant_priced_listings,
        is_priced_product_listing,
        listing_relevant_to_query,
    )
    from app.utils.spec_check import annotate_listings_with_spec_check

    rows = annotate_listing_channels(list(listings or []), is_bulk=False)
    rows, _ = annotate_listings_with_spec_check(rows, query or "")
    kept, _dropped, _meta = filter_relevant_priced_listings(rows, query or "", is_bulk=False)

    # Soften if the hard filter left too few — still require product URL + digit price
    if len(kept) < 3:
        soft: list[dict[str, Any]] = []
        seen = {str(r.get("link") or "") for r in kept}
        for row in rows:
            link = str(row.get("link") or "")
            if link in seen:
                continue
            if not is_priced_product_listing(row):
                continue
            if query and not listing_relevant_to_query(row, query):
                continue
            price = str(row.get("price") or "")
            if re.match(r"^(see\s+listing|n/?a|rs\.?|pkr|usd|\$)[\s,.…]*$", price, re.I):
                continue
            soft.append(row)
            seen.add(link)
            if len(kept) + len(soft) >= limit:
                break
        kept = kept + soft

    cur = (currency or "").strip().upper()
    # Prefer rows already in seller currency; flag mismatches when market-service didn't
    for row in kept:
        if cur and not row.get("currency_mismatch"):
            detected = str(row.get("currency") or "").strip().upper()
            price_l = str(row.get("price") or "").lower()
            looks_foreign = bool(
                re.search(r"\$|usd|£|gbp|€|eur", price_l)
                and cur not in ("USD", "GBP", "EUR")
            )
            if detected and detected != cur:
                row["currency_mismatch"] = True
            elif looks_foreign and cur in ("PKR", "INR", "AED"):
                row["currency_mismatch"] = True

    local = sorted(
        [r for r in kept if not r.get("currency_mismatch")],
        key=_sort_key_price,
    )
    foreign = sorted(
        [r for r in kept if r.get("currency_mismatch")],
        key=_sort_key_price,
    )

    # ~70% local live comps, ~30% foreign reference (never foreign-only when local exists)
    local_slots = max(5, int(limit * 0.7)) if local else 0
    foreign_slots = max(0, limit - min(len(local), local_slots))
    if not local:
        foreign_slots = min(len(foreign), limit)
    elif foreign:
        foreign_slots = max(2, min(foreign_slots, 3, len(foreign)))
        local_slots = limit - foreign_slots

    out = local[:local_slots] + foreign[:foreign_slots]
    # Fill if either side was thin
    if len(out) < limit:
        used = {str(r.get("link") or "") for r in out}
        for row in local + foreign:
            link = str(row.get("link") or "")
            if link in used:
                continue
            out.append(row)
            used.add(link)
            if len(out) >= limit:
                break
    return out[:limit]


def build_price_explanation(
    *,
    listings: list[dict[str, Any]],
    currency: str,
    price_min: str | None,
    price_max: str | None,
    recommended_price: str | None,
    cost_of_goods: str | None = None,
    target_margin_pct: str | None = None,
) -> dict[str, Any]:
    local_nums = listing_numbers(listings, local_only=True)
    all_nums = listing_numbers(listings, local_only=False)
    foreign_count = sum(1 for r in listings or [] if r.get("currency_mismatch"))
    local_count = len(listings or []) - foreign_count
    med_local = median(local_nums)
    med_all = median(all_nums)
    band_min = parse_money(price_min)
    band_max = parse_money(price_max)
    # If seller swapped min/max, normalize before messaging.
    if band_min is not None and band_max is not None and band_min > band_max:
        band_min, band_max = band_max, band_min
    rec = parse_money(recommended_price)
    cogs = parse_money(cost_of_goods)
    margin_target = parse_money(target_margin_pct)

    floor_from_cogs = None
    if cogs is not None and margin_target is not None and margin_target < 100:
        # price = cogs / (1 - margin/100)
        denom = 1 - (margin_target / 100.0)
        if denom > 0.05:
            floor_from_cogs = cogs / denom

    med_label = format_amount(med_local, currency) if med_local is not None else None
    rec_label = format_amount(rec, currency) if rec is not None else None
    band_max_label = format_amount(band_max, currency) if band_max is not None else None
    band_min_label = format_amount(band_min, currency) if band_min is not None else None

    if local_count == 0 and foreign_count > 0:
        why = (
            "Local comps are missing — live results are foreign-currency only. "
            "Treat them as international reference; stay inside your stated price band."
        )
        data_quality = "thin_foreign"
    elif local_count == 0:
        why = (
            "No live seller prices were retrieved. Advice leans on your product details "
            "and stated price band — not a market median."
        )
        data_quality = "empty"
    elif local_count < 3:
        why = (
            f"Only {local_count} local live price(s)"
            + (f" (median about {med_label})" if med_label else "")
            + ". Treat the suggestion as directional, not a precise market median."
        )
        data_quality = "thin_local"
    else:
        base = f"Based on {local_count} local live prices"
        if med_label:
            base += f" (median about {med_label})"
        if rec is not None and med_local is not None:
            gap = _pct_gap(rec, med_local)
            if gap <= 10:
                why = (
                    f"{base}. Suggested {rec_label} sits close to that local median "
                    "and stays inside your stated band where possible."
                )
            elif rec < med_local:
                why = (
                    f"{base}. Local sellers ask around {med_label}; suggested {rec_label} "
                    "is below that cluster"
                )
                if band_max is not None and rec <= band_max + 1e-9 and med_local > band_max:
                    why += (
                        f" because your max is {band_max_label} — you are pricing under the "
                        "local market."
                    )
                else:
                    why += " (useful for volume; weaker if you need higher margin)."
            else:
                why = (
                    f"{base}. Suggested {rec_label} sits above the local median ({med_label}) "
                    "— only hold that if your product is clearly better than typical comps."
                )
        elif rec_label:
            why = f"{base}. Suggested list is {rec_label}."
        else:
            why = f"{base}."
        data_quality = "ok"

    vs_band = ""
    if rec is not None and band_min is not None and band_max is not None:
        if rec < band_min:
            if med_local is not None and med_local < band_min:
                vs_band = (
                    "Suggested price tracks local comps, which sit below your stated low end — "
                    "either raise your list toward your band or lower the band to match the market."
                )
            else:
                vs_band = "Suggested price is below your low end — consider raising or checking costs."
        elif rec > band_max:
            vs_band = "Suggested price is above your high end — only if comps and demand justify it."
        else:
            if med_local is not None and med_local > band_max and _pct_gap(med_local, band_max) > 10:
                vs_band = (
                    f"Inside your band ({band_min_label} – {band_max_label}), but local median "
                    f"({med_label}) is higher — raise your max if you want to match the market."
                )
            elif med_local is not None and med_local < band_min and _pct_gap(band_min, med_local) > 10:
                vs_band = (
                    f"Inside your band, but local median ({med_label}) is below your low end — "
                    "the market may not support the top of your range."
                )
            else:
                vs_band = "Suggested price sits inside your stated band."
    elif rec is not None and med_local is not None:
        gap = _pct_gap(rec, med_local)
        if gap <= 10:
            vs_band = "Suggested price is close to the local median."
        elif rec < med_local:
            vs_band = "Suggested price is below the local median."
        else:
            vs_band = "Suggested price is above the local median."

    promo_floor = None
    if floor_from_cogs is not None:
        promo_floor = floor_from_cogs
    elif band_min is not None:
        promo_floor = band_min
    elif med_local is not None:
        promo_floor = med_local * 0.9

    list_anchor = rec or med_local or band_max or band_min

    # Promo floor must stay BELOW the list price (never a "sale" above list).
    if list_anchor is not None and promo_floor is not None and promo_floor >= list_anchor:
        promo_floor = max(list_anchor * 0.85, (floor_from_cogs or 0))
        if promo_floor >= list_anchor:
            promo_floor = list_anchor * 0.9
    if list_anchor is not None and promo_floor is None:
        promo_floor = list_anchor * 0.9

    return {
        "currency": (currency or "").upper(),
        "local_listing_count": max(0, local_count),
        "foreign_listing_count": foreign_count,
        "median_local": format_amount(med_local, currency) if med_local else None,
        "median_all": format_amount(med_all, currency) if med_all else None,
        "recommended": format_amount(rec, currency) if rec else (recommended_price or None),
        "your_band": (
            f"{format_amount(band_min, currency)} – {format_amount(band_max, currency)}"
            if band_min is not None or band_max is not None
            else None
        ),
        "list_price_suggestion": format_amount(list_anchor, currency) if list_anchor else None,
        "promo_floor": format_amount(promo_floor, currency) if promo_floor else None,
        "cost_floor": format_amount(floor_from_cogs, currency) if floor_from_cogs else None,
        "why": why,
        "vs_your_band": vs_band,
        "data_quality": data_quality,
    }
