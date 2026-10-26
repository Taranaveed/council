"""Price plausibility: reject outlier / implausible unit prices within a result set."""
from __future__ import annotations

import re
from typing import Any

from app.utils.money import parse_money, is_malformed_price_string, sanitize_price_raw

# Rough USD band per loose category (min, max). Soft secondary bound.
_CATEGORY_USD_BANDS: list[tuple[str, float, float]] = [
    (r"mug|cup|ceramic", 0.15, 80.0),
    (r"thermos|flask|bottle", 0.5, 120.0),
    (r"earphone|earbud|handsfree|headset|headphone", 0.2, 150.0),
    (r"adapter|charger|otg|cable", 0.1, 80.0),
    (r"cover|case|phonecase", 0.15, 60.0),
    (r"ring|rings|jewellery|jewelry", 0.2, 500.0),
]


def _to_usd_approx(amount: float, currency: str | None) -> float | None:
    """Lightweight FX for outlier math only (not for display)."""
    rates = {
        "USD": 1.0,
        "PKR": 0.0036,
        "INR": 0.012,
        "AED": 0.27,
        "SAR": 0.27,
        "GBP": 1.27,
        "EUR": 1.08,
        "CAD": 0.73,
        "AUD": 0.66,
        "SGD": 0.74,
        "CNY": 0.14,
    }
    cur = (currency or "USD").upper()
    if cur.startswith("LOCAL"):
        cur = "USD"
    r = rates.get(cur)
    if not r or amount <= 0:
        return None
    return amount * r


def _detect_currency(price: str, fallback: str = "USD") -> str:
    text = str(price or "")
    if re.search(r"\$|USD", text, re.I):
        return "USD"
    if re.search(r"Rs\.?|PKR", text, re.I):
        return "PKR"
    if re.search(r"₹|INR", text, re.I):
        return "INR"
    if re.search(r"£|GBP", text, re.I):
        return "GBP"
    if re.search(r"€|EUR", text, re.I):
        return "EUR"
    return (fallback or "USD").upper()


def _listing_usd(listing: dict[str, Any]) -> float | None:
    if listing.get("unit_usd") is not None:
        try:
            n = float(listing["unit_usd"])
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
    amt = parse_money(listing.get("price"))
    if amt is None or amt <= 0:
        return None
    cur = _detect_currency(
        str(listing.get("price") or ""),
        str(listing.get("currency") or "USD"),
    )
    return _to_usd_approx(amt, cur)


def _blob(listing: dict[str, Any]) -> str:
    parts = [
        str(listing.get("title") or ""),
        str(listing.get("snippet") or ""),
        str(listing.get("note") or ""),
    ]
    return " ".join(parts).lower()


def annotate_implausible_metal_prices(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Hard-mark solid-gold / sterling quotes that are physically implausible.
    Callers must exclude these from ranking and landed-cost (not flag-only).
    """
    rows = [dict(x) for x in (listings or [])]
    for row in rows:
        if row.get("price_outlier") or row.get("unit_price_unreliable"):
            continue
        blob = _blob(row)
        price = str(row.get("price") or "")
        amt = parse_money(price)
        if amt is None or amt <= 0:
            continue
        # Solid gold (not plated) under ~$80 USD-equivalent for a piece
        if re.search(r"\b18\s*k|\b22\s*k|\b24\s*k|\b(solid\s+)?gold\b", blob) and not re.search(
            r"\b(plated|filled|vermeil|colour|color|tone|gold.?color)\b", blob
        ):
            usdish = _listing_usd(row)
            if usdish is not None and usdish < 80:
                row["price_outlier"] = True
                row["implausible_metal"] = "gold"
                row["unit_price_unreliable"] = True
                row["counts_as_live_listing"] = False
                row["price_outlier_reason"] = (
                    f"Implausible solid-gold unit ≈ ${usdish:.2f} — likely plated, per-lot, "
                    "or a bad scrape. Price could not be reliably parsed."
                )
                continue
        # Sterling / 925 under $1.50 USD
        if re.search(r"\b925\b|\bsterling\b", blob) or (
            re.search(r"\bsilver\b", blob)
            and not re.search(r"\b(plated|colour|color|tone)\b", blob)
        ):
            usdish = _listing_usd(row)
            if usdish is not None and usdish < 1.5 and re.search(r"\$|usd", price, re.I):
                row["price_outlier"] = True
                row["implausible_metal"] = "silver"
                row["unit_price_unreliable"] = True
                row["counts_as_live_listing"] = False
                row["price_outlier_reason"] = (
                    f"Implausible sterling/silver unit ≈ ${usdish:.2f} — verify unit vs lot. "
                    "Price could not be reliably parsed."
                )
    return rows


def annotate_price_outliers(
    listings: list[dict[str, Any]],
    *,
    query: str = "",
    max_median_ratio: float = 5.0,
) -> list[dict[str, Any]]:
    """
    Flag listings whose unit USD is >max_median_ratio× peer median (default 5×)
    or <20% of peer median. Also marks implausible metal quotes. Callers must exclude.
    """
    rows = annotate_implausible_metal_prices([dict(x) for x in (listings or [])])

    # Malformed display strings (unit+MOQ concat) — flag even before median math
    for row in rows:
        raw = str(row.get("price") or "")
        if is_malformed_price_string(raw):
            rescued = sanitize_price_raw(raw)
            n = parse_money(rescued)
            row["price_outlier"] = True
            row["unit_price_unreliable"] = True
            row["counts_as_live_listing"] = False
            row["price_outlier_reason"] = (
                f"Malformed price “{raw[:48]}” — likely unit+MOQ concatenation "
                "or bad scrape; check listing directly."
            )
            if n is not None and n > 0:
                # Keep a cleaned display so users aren't shown "$1.321,000"
                cur = "USD" if "$" in raw or "USD" in raw.upper() else str(row.get("currency") or "USD")
                if cur.upper() == "USD":
                    row["price"] = f"${n:.2f}" if n < 10 else f"${n:,.0f}"
                row["price_malformed_original"] = raw
            else:
                row["price"] = "See listing"
                row["needs_price_confirm"] = True

    usd_vals: list[tuple[int, float]] = []
    for i, row in enumerate(rows):
        u = _listing_usd(row)
        if u is not None:
            usd_vals.append((i, u))

    if len(usd_vals) < 3:
        return _apply_category_bands(rows, query)

    sorted_u = sorted(u for _, u in usd_vals)
    median = sorted_u[len(sorted_u) // 2]
    if median <= 0:
        return rows

    for i, u in usd_vals:
        if rows[i].get("price_outlier"):
            continue
        # UK retail Shopping comps are a different channel than factory imports —
        # do not peer-median them against Alibaba/DHgate unit prices.
        if rows[i].get("uk_retail_priced"):
            continue
        # High: >max_median_ratio× median (default 5×). Low: <20% of peer median.
        if u > median * max_median_ratio or u < median * 0.20:
            rows[i]["price_outlier"] = True
            rows[i]["price_implausible"] = True
            rows[i]["price_flagged"] = True
            why = (
                f">={max_median_ratio:.0f}x_peer_median"
                if u > median * max_median_ratio
                else "<20pct_peer_median"
            )
            rows[i]["price_flag_reasons"] = list(
                dict.fromkeys((rows[i].get("price_flag_reasons") or []) + [why])
            )
            rows[i]["price_outlier_reason"] = (
                f"unit ≈ ${u:.2f} USD vs peer median ≈ ${median:.2f} "
                f"(>{max_median_ratio:.0f}× or <20% of median) — price could not be reliably parsed"
            )
            rows[i]["counts_as_live_listing"] = False
            if not rows[i].get("unit_price_rejected"):
                rows[i]["unit_price_unreliable"] = True
    return _apply_uk_category_bands(rows, query)


def _apply_uk_category_bands(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """GBP floor/ceiling from shared/price_bands/uk_categories.json (+ legacy USD bands)."""
    from app.utils.price_bands import assess_category_band

    for row in rows:
        if row.get("price_outlier") and row.get("price_flagged"):
            # still also run category for richer reasons
            pass
        u_usd = _listing_usd(row)
        if u_usd is None:
            continue
        # Approx USD→GBP for band check (bands file is GBP)
        unit_gbp = u_usd / 1.27
        pt = row.get("price_type")
        if row.get("uk_retail_priced"):
            pt = "retail"
        assessment = assess_category_band(unit_gbp, query, price_type=pt)
        if not assessment.get("in_band"):
            reasons = assessment.get("reasons") or []
            # Soft (within 3×): flag but do not mark unreliable / hide
            if assessment.get("soft_flag") or (
                assessment.get("soft_guards") and not assessment.get("hard_guards")
            ):
                row["price_soft_flagged"] = True
                row["price_flagged"] = True
                row["price_flag_reasons"] = list(
                    dict.fromkeys(
                        (row.get("price_flag_reasons") or [])
                        + [f"soft_{r}" for r in reasons]
                    )
                )
                band = assessment.get("band") or {}
                row["price_outlier_reason"] = (
                    f"soft flag: unit ≈ £{unit_gbp:.2f} within 3× of "
                    f"{band.get('table')} band £{band.get('floor_gbp')}–£{band.get('ceiling_gbp')}"
                )
            else:
                row["price_outlier"] = True
                row["price_implausible"] = True
                row["price_flagged"] = True
                row["price_flag_reasons"] = list(
                    dict.fromkeys((row.get("price_flag_reasons") or []) + list(reasons))
                )
                band = assessment.get("band") or {}
                row["price_outlier_reason"] = (
                    f"unit ≈ £{unit_gbp:.2f} outside category band "
                    f"£{band.get('floor_gbp')}–£{band.get('ceiling_gbp')} "
                    f"({band.get('id')}/{band.get('table')})"
                )
                row["counts_as_live_listing"] = False
                row["unit_price_unreliable"] = True
    # Keep legacy USD soft bands as additional signal
    return _apply_category_bands(rows, query)


def _apply_category_bands(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    q = str(query or "").lower()
    band = None
    for pat, lo, hi in _CATEGORY_USD_BANDS:
        if re.search(pat, q, re.I):
            band = (lo, hi)
            break
    if not band:
        return rows
    lo, hi = band
    for row in rows:
        if row.get("price_outlier"):
            continue
        u = _listing_usd(row)
        if u is None:
            continue
        if u < lo or u > hi:
            row["price_outlier"] = True
            row["price_outlier_reason"] = (
                f"unit ≈ ${u:.2f} USD outside expected band ${lo:.2f}–${hi:.2f} "
                f"for this category — price could not be reliably parsed"
            )
            row["counts_as_live_listing"] = False
            row["unit_price_unreliable"] = True
    return rows
