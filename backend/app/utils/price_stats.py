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
    rec = parse_money(recommended_price)
    cogs = parse_money(cost_of_goods)
    margin_target = parse_money(target_margin_pct)

    floor_from_cogs = None
    if cogs is not None and margin_target is not None and margin_target < 100:
        # price = cogs / (1 - margin/100)
        denom = 1 - (margin_target / 100.0)
        if denom > 0.05:
            floor_from_cogs = cogs / denom

    if local_count == 0 and foreign_count > 0:
        why = (
            "Local comps are missing — live results are foreign-currency only. "
            "Treat them as international reference; stay inside your stated price band."
        )
        data_quality = "thin_foreign"
    elif local_count == 0:
        why = (
            "No live seller prices were retrieved. Advice leans on your product details "
            "and stated price band — not a verified local median."
        )
        data_quality = "empty"
    elif local_count < 3:
        why = (
            f"Only {local_count} local live price(s). Use the suggested band as a guide, "
            "not a precise market median."
        )
        data_quality = "thin_local"
    else:
        why = (
            f"Based on {local_count} local live prices"
            + (f" (median about {format_amount(med_local, currency)})" if med_local else "")
            + ". Suggested price sits near that cluster while respecting your band."
        )
        data_quality = "ok"

    # If seller swapped min/max, normalize for messaging and promo math.
    if band_min is not None and band_max is not None and band_min > band_max:
        band_min, band_max = band_max, band_min

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
            vs_band = "Suggested price is above your high end — premium only if proof of quality/demand."
        else:
            vs_band = "Suggested price sits inside your stated band."

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
