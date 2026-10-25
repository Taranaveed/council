"""Deterministic landed-cost estimate with stated assumptions and a low–high range."""
from __future__ import annotations

import re
from typing import Any

from app.core.region_profile import get_profile
from app.utils.cost_assumptions import (
    FREIGHT_USD_PER_KG,
    SHIPPING_FLAT_BY_CURRENCY,
    infer_listing_origin,
    shared_cost_assumptions,
)
from app.utils.fx import convert_amount
from app.utils.money import parse_money
from app.utils.tier_select import select_tier_for_quantity

# (title regex, assumed kg/unit, max plausible kg/unit, min plausible)
_CATEGORY_WEIGHT_KG = [
    (
        re.compile(
            r"\b(phone\s*case|iphone\s*case|mobile\s*(?:case|cover)|back\s*cover|alcantara\s*(?:case|cover)|silicone\s*case)\b",
            re.I,
        ),
        0.05,
        0.35,
        0.005,
    ),
    (re.compile(r"\b(earphone|earbud|handsfree|headset)\b", re.I), 0.05, 0.25, 0.005),
    (re.compile(r"\b(adapter|charger|cable|otg)\b", re.I), 0.08, 0.5, 0.01),
    (re.compile(r"\b(jewel|ring|earring|pendant|necklace)\b", re.I), 0.02, 0.08, 0.001),
    (re.compile(r"\b(mist|spray|perfume|bottle)\b", re.I), 0.20, 1.0, 0.02),
]

# Assumed kg/unit when page has no weight (labelled as assumption).
_ASSUMED_KG_PER_UNIT = 0.15
_DEFAULT_MAX_KG = 2.0
_DEFAULT_MIN_KG = 0.005
_WEIGHT_OVER_ASSUMED_REJECT = 10.0  # ignore page weight if >10× category assumed


def _category_weight_profile(listing: dict[str, Any]) -> tuple[float, float, float]:
    """Return (assumed_kg, max_plausible_kg, min_plausible_kg)."""
    blob = f"{listing.get('title') or ''} {listing.get('snippet') or ''}"
    for cre, assumed, max_kg, min_kg in _CATEGORY_WEIGHT_KG:
        if cre.search(blob):
            return float(assumed), float(max_kg), float(min_kg)
    return _ASSUMED_KG_PER_UNIT, _DEFAULT_MAX_KG, _DEFAULT_MIN_KG


def _category_weight_kg(listing: dict[str, Any]) -> float:
    return _category_weight_profile(listing)[0]


def resolve_unit_weight_kg(
    listing: dict[str, Any],
    *,
    foreign: bool,
) -> dict[str, Any]:
    """
    Resolve per-unit kg for freight.

    Ignores page weights that look like carton/gross (or are implausible for the
    category / >10× assumed default). Returns diagnostic fields for brief/smoke.
    """
    assumed, max_kg, min_kg = _category_weight_profile(listing)
    raw_text = str(listing.get("package_weight_raw") or "") or None
    basis = str(listing.get("package_weight_basis") or "").lower() or None
    pcs = listing.get("package_weight_pcs_per_carton")
    try:
        pcs_n = int(pcs) if pcs is not None else None
    except (TypeError, ValueError):
        pcs_n = None
    kg_as_parsed = listing.get("package_weight_kg_as_parsed")
    try:
        kg_as_parsed_f = float(kg_as_parsed) if kg_as_parsed is not None else None
    except (TypeError, ValueError):
        kg_as_parsed_f = None

    weight_src = str(listing.get("package_weight_source") or "").lower()
    try:
        page_kg = (
            float(listing["package_weight_kg"])
            if listing.get("package_weight_kg") is not None
            else None
        )
    except (TypeError, ValueError):
        page_kg = None

    # Carton/gross without usable per-unit conversion
    if basis in ("carton", "gross") and (page_kg is None or page_kg <= 0):
        note = str(listing.get("package_weight_note") or "") or (
            "page weight ignored (looked like carton/gross weight)"
        )
        if not foreign:
            return {
                "kg": None,
                "from_page": False,
                "ignored": True,
                "ignore_reason": note,
                "assumed_kg": assumed,
                "raw": raw_text,
                "basis": basis,
                "pcs_per_carton": pcs_n,
                "kg_as_parsed": kg_as_parsed_f,
                "how": f"raw={raw_text!r} basis={basis} → not used as per-unit; {note}",
            }
        return {
            "kg": assumed,
            "from_page": False,
            "ignored": True,
            "ignore_reason": note,
            "assumed_kg": assumed,
            "raw": raw_text,
            "basis": basis,
            "pcs_per_carton": pcs_n,
            "kg_as_parsed": kg_as_parsed_f,
            "how": (
                f"raw={raw_text!r} basis={basis} kg_as_parsed={kg_as_parsed_f} "
                f"pcs/carton={pcs_n} → ignored; using assumed {assumed} kg/unit "
                f"({note})"
            ),
        }

    if page_kg is not None and page_kg > 0 and weight_src in (
        "page",
        "page_facts",
        "html",
        "snippet",
    ):
        how_ok = (
            f"raw={raw_text!r} basis={basis or 'unknown'} "
            f"kg_as_parsed={kg_as_parsed_f if kg_as_parsed_f is not None else page_kg}"
        )
        if pcs_n and kg_as_parsed_f and basis in ("carton", "gross"):
            how_ok += f" ÷ {pcs_n} pcs/carton → {page_kg} kg/unit"
        else:
            how_ok += f" → treated as {page_kg} kg/unit ({weight_src})"

        over_assumed = page_kg > (assumed * _WEIGHT_OVER_ASSUMED_REJECT)
        out_of_range = page_kg > max_kg or page_kg < min_kg
        if over_assumed or out_of_range:
            reason = "page weight ignored (looked like carton/gross weight)"
            detail = (
                f"{page_kg:g} kg/unit outside plausible "
                f"[{min_kg:g}–{max_kg:g}] or >{_WEIGHT_OVER_ASSUMED_REJECT:g}× "
                f"assumed {assumed:g}"
            )
            if not foreign:
                return {
                    "kg": None,
                    "from_page": False,
                    "ignored": True,
                    "ignore_reason": reason,
                    "assumed_kg": assumed,
                    "raw": raw_text,
                    "basis": basis,
                    "pcs_per_carton": pcs_n,
                    "kg_as_parsed": kg_as_parsed_f or page_kg,
                    "how": f"{how_ok}; rejected ({detail})",
                }
            return {
                "kg": assumed,
                "from_page": False,
                "ignored": True,
                "ignore_reason": reason,
                "assumed_kg": assumed,
                "raw": raw_text,
                "basis": basis,
                "pcs_per_carton": pcs_n,
                "kg_as_parsed": kg_as_parsed_f or page_kg,
                "how": (
                    f"{how_ok}; rejected ({detail}) → using assumed "
                    f"{assumed} kg/unit ({reason})"
                ),
            }

        return {
            "kg": page_kg,
            "from_page": weight_src in ("page", "page_facts", "html"),
            "ignored": False,
            "ignore_reason": None,
            "assumed_kg": assumed,
            "raw": raw_text,
            "basis": basis or "unit",
            "pcs_per_carton": pcs_n,
            "kg_as_parsed": kg_as_parsed_f or page_kg,
            "how": how_ok,
        }

    if foreign:
        return {
            "kg": assumed,
            "from_page": False,
            "ignored": False,
            "ignore_reason": None,
            "assumed_kg": assumed,
            "raw": raw_text,
            "basis": "assumed",
            "pcs_per_carton": pcs_n,
            "kg_as_parsed": kg_as_parsed_f,
            "how": (
                f"no usable page unit weight (raw={raw_text!r}) → "
                f"assumed {assumed} kg/unit for category"
            ),
        }
    return {
        "kg": None,
        "from_page": False,
        "ignored": False,
        "ignore_reason": None,
        "assumed_kg": assumed,
        "raw": raw_text,
        "basis": "none",
        "pcs_per_carton": pcs_n,
        "kg_as_parsed": kg_as_parsed_f,
        "how": f"domestic / no weight — raw={raw_text!r}",
    }


# Legacy static FX table — used only as convert_amount fallback when live FX fails.
_TO_USD = {
    "USD": 1.0,
    "PKR": 1 / 278,
    "INR": 1 / 83,
    "AED": 1 / 3.67,
    "SAR": 1 / 3.75,
    "GBP": 1.27,
    "EUR": 1.08,
    "CAD": 0.74,
    "AUD": 0.65,
    "SGD": 0.74,
    "BDT": 1 / 110,
    "TRY": 1 / 34,
    "EGP": 1 / 48,
    "MYR": 1 / 4.7,
}

# Fallback flat shipping when weight is unknown (local currency) — prefer profile.
_SHIPPING_FLAT = dict(SHIPPING_FLAT_BY_CURRENCY)


def _parse_amount(raw: Any) -> float | None:
    return parse_money(raw)


_FACTORY_USD_HOST = re.compile(
    r"alibaba\.|made-in-china\.|dhgate\.|globalsources\.|aliexpress\.|1688\.",
    re.I,
)


def _is_factory_usd_host(listing: dict[str, Any] | None) -> bool:
    if not listing or not isinstance(listing, dict):
        return False
    blob = f"{listing.get('link') or ''} {listing.get('vendor') or ''}"
    if _FACTORY_USD_HOST.search(blob):
        return True
    if listing.get("wholesale") or str(listing.get("supplier_origin") or "").upper() == "CN":
        return True
    return False


def _detect_currency(
    price: str,
    fallback: str = "USD",
    *,
    listing: dict[str, Any] | None = None,
) -> str:
    """
    Prefer explicit symbols in the price string. Never let a buyer-market
    preferred currency override a $ marker. Factory/B2B hosts (Alibaba etc.)
    quote USD — even when a page scrape rewrote the display as £ under a UK
    preferredCurrency — so they always resolve as USD unless the string is an
    explicit non-USD amount with no $ (rare; still prefer USD for these hosts).
    """
    text = str(price or "")
    if re.search(r"\$|USD|US\s*\$", text, re.I):
        return "USD"
    # Factory/B2B: USD quoting is the norm; buyer-locale £/Rs rewrites are bugs
    if _is_factory_usd_host(listing):
        return "USD"
    if re.search(r"Rs\.?|PKR", text, re.I):
        return "PKR"
    if re.search(r"₹|INR", text, re.I):
        return "INR"
    if re.search(r"£|GBP", text, re.I):
        return "GBP"
    if re.search(r"€|EUR", text, re.I):
        return "EUR"
    if re.search(r"AED", text, re.I):
        return "AED"
    if re.search(r"SAR", text, re.I):
        return "SAR"
    listed = str((listing or {}).get("currency") or "").upper().strip()
    if listed in ("USD", "PKR", "INR", "GBP", "EUR", "AED", "SAR", "CAD", "AUD"):
        return listed
    return (fallback or "USD").upper()


def _fx_fallback_for(currency: str, profile: dict[str, Any] | None = None) -> float | None:
    cur = (currency or "").upper()
    if profile and str(profile.get("currency") or "").upper() == cur:
        try:
            fb = float(profile.get("fx_to_usd_fallback") or 0)
            if fb > 0:
                return fb
        except (TypeError, ValueError):
            pass
    return _TO_USD.get(cur)


def _to_local(
    amount: float,
    from_cur: str,
    to_cur: str,
    *,
    fx_meta_out: list | None = None,
    profile: dict[str, Any] | None = None,
) -> float | None:
    converted, meta = convert_amount(
        amount,
        from_cur,
        to_cur,
        from_fallback=_fx_fallback_for(from_cur, profile),
        to_fallback=_fx_fallback_for(to_cur, profile),
    )
    if fx_meta_out is not None:
        fx_meta_out.append(meta)
    return converted


def _fmt(amount: float, currency: str) -> str:
    cur = (currency or "USD").upper()
    if cur == "USD":
        return f"${amount:,.2f}" if amount < 10 else f"${amount:,.0f}"
    if cur == "PKR":
        return f"Rs {amount:,.0f}"
    if cur == "INR":
        return f"₹{amount:,.0f}"
    if cur == "GBP":
        return f"£{amount:,.2f}" if amount < 10 else f"£{amount:,.0f}"
    if cur == "EUR":
        return f"€{amount:,.2f}" if amount < 10 else f"€{amount:,.0f}"
    return f"{amount:,.2f} {cur}"


def _tiers_are_verified(listing: dict[str, Any]) -> bool:
    """Only page-sourced tiers may drive the primary unit price."""
    src = str(listing.get("tiers_source") or "").lower()
    if src not in ("page", "page_scalar"):
        return False
    if listing.get("tiers_reliable") is False:
        return False
    if listing.get("unit_price_verified") is False:
        return False
    return True


def _pick_tier(
    listing: dict[str, Any],
    quantity: int,
    *,
    allow_tiers: bool = True,
) -> tuple[float, str, int | None, str]:
    """Return (unit_amount, unit_currency, moq, source_label)."""
    card_amt = _parse_amount(listing.get("price"))
    card_cur = _detect_currency(
        str(listing.get("price") or ""),
        str(listing.get("currency") or "USD"),
        listing=listing,
    )

    # Reject storefront / missing extracted unit prices
    if listing.get("unit_price_rejected") or str(listing.get("price_source") or "").lower() == "rejected_storefront":
        return 0.0, card_cur, None, "rejected_storefront"
    if listing.get("price_outlier") or listing.get("unit_price_unreliable") or listing.get("implausible_metal"):
        return 0.0, card_cur, None, "unreliable_price"
    if not listing.get("is_product_page", True) and listing.get("is_product_page") is False:
        return 0.0, card_cur, None, "not_product_page"

    tiers = listing.get("price_tiers")
    if allow_tiers and _tiers_are_verified(listing) and isinstance(tiers, list) and tiers:
        usable: list[tuple[int, float, str]] = []
        for row in tiers:
            if not isinstance(row, dict):
                continue
            min_qty = int(row.get("min_qty") or 1)
            cur = str(row.get("currency") or listing.get("currency") or card_cur or "USD").upper()
            amt = _parse_amount(row.get("unit_price") or row.get("price"))
            if amt is None and row.get("unit_usd") is not None:
                try:
                    amt = float(row["unit_usd"])
                    cur = "USD"
                except (TypeError, ValueError):
                    amt = None
            if amt is None:
                continue
            # Same-currency agreement with card (never treat $3.30 ≈ Rs 3)
            if card_amt and card_amt > 0:
                if cur != card_cur:
                    # Convert both to card currency before comparing
                    card_in_tier = _to_local(card_amt, card_cur, cur)
                    if card_in_tier is None or card_in_tier <= 0:
                        continue
                    if abs(amt - card_in_tier) / max(amt, card_in_tier) > 0.35:
                        continue
                elif abs(amt - card_amt) / max(amt, card_amt) > 0.35:
                    continue
            usable.append((min_qty, amt, cur))
        if usable:
            usable.sort(key=lambda x: x[0])
            chosen = usable[0]
            for min_qty, amt, cur in usable:
                if quantity >= min_qty:
                    chosen = (min_qty, amt, cur)
            return chosen[1], chosen[2], chosen[0], f"page tier >={chosen[0]} units"
        if card_amt and card_amt > 0:
            moq = listing.get("moq")
            moq_n = None
            try:
                if moq is not None:
                    moq_n = int(moq)
            except (TypeError, ValueError):
                moq_n = None
            return card_amt, card_cur, moq_n, "listing price (tiers disagreed)"

    unit_usd = listing.get("unit_usd")
    if unit_usd is not None and str(listing.get("price_source") or "").lower() in (
        "page",
        "tier",
        "tier_selected",
        "page_scalar",
        "",
    ):
        try:
            n = float(unit_usd)
            if n > 0:
                moq = listing.get("moq")
                moq_n = int(moq) if moq is not None and str(moq).isdigit() else None
                return n, "USD", moq_n, "unit_usd"
        except (TypeError, ValueError):
            pass

    price = str(listing.get("price") or "")
    amt = _parse_amount(price)
    cur = _detect_currency(
        price, str(listing.get("currency") or "USD"), listing=listing
    )
    moq = listing.get("moq")
    moq_n = None
    try:
        if moq is not None:
            moq_n = int(moq)
    except (TypeError, ValueError):
        moq_n = None
    if amt is not None:
        src = str(listing.get("price_source") or "listing").lower()
        label = "listing price"
        if src in ("serp", "snippet"):
            label = "listing price (serp — unverified)"
        elif src in ("page", "page_scalar"):
            label = "listing price (page)"
        return amt, cur, moq_n, label
    return 0.0, cur, moq_n, "unpriced"


def _is_foreign_factory(listing: dict[str, Any]) -> bool:
    link = str(listing.get("link") or "")
    origin = str(listing.get("supplier_origin") or "").upper()
    if origin == "CN":
        return True
    return bool(
        re.search(
            r"alibaba\.|made-in-china\.|dhgate\.|globalsources\.|aliexpress\.|1688\.",
            link,
            re.I,
        )
    )


def _shipping_band(
    *,
    foreign: bool,
    qty: int,
    weight_kg_unit: float | None,
    weight_from_page: bool,
    local: str,
    freight_usd_per_kg: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """
    Return ({low, mid, high} shipping in local currency, meta).
    Prefers weight × freight $/kg; falls back to flat when weight unknown.
    """
    rates = freight_usd_per_kg or FREIGHT_USD_PER_KG
    meta: dict[str, Any] = {
        "weight_kg_unit": weight_kg_unit,
        "weight_from_page": weight_from_page,
        "freight_usd_per_kg_low": rates["low"],
        "freight_usd_per_kg_mid": rates["mid"],
        "freight_usd_per_kg_high": rates["high"],
    }
    if not foreign:
        return {"low": 0.0, "mid": 0.0, "high": 0.0}, {
            **meta,
            "method": "local_no_shipping",
            "freight_assumption": "No inbound freight (treated as domestic / local listing)",
        }

    if weight_kg_unit and weight_kg_unit > 0:
        total_kg = weight_kg_unit * qty
        meta["total_kg"] = round(total_kg, 3)
        band = {}
        for key in ("low", "mid", "high"):
            usd = total_kg * float(rates[key])
            local_amt = _to_local(usd, "USD", local) or usd
            band[key] = float(local_amt)
        src = (
            "page weight"
            if weight_from_page
            else "weight not confirmed on page (assumed for band only)"
        )
        meta["method"] = "weight_x_freight"
        meta["freight_assumption"] = (
            f"{src}; freight ${float(rates['low']):.0f}–"
            f"${float(rates['high']):.0f}/kg air (mid ${float(rates['mid']):.0f}/kg)"
        )
        return band, meta

    flat = float(_SHIPPING_FLAT.get(local, 50))
    meta["method"] = "flat_fallback"
    meta["freight_assumption"] = (
        f"Package weight not on page — flat inbound placeholder {_fmt(flat, local)} "
        f"(not a carrier quote); mid band ±40%"
    )
    meta["flat_shipping"] = {
        "amount": flat,
        "currency": local,
        "effective_date": None,
        "source_url": "assumption://shipping-flat-by-currency",
        "label": "Flat inbound placeholder when weight unknown",
    }
    return {"low": flat * 0.6, "mid": flat, "high": flat * 1.4}, meta


def compute_landed_cost(
    listing: dict[str, Any] | None,
    *,
    quantity: int | None,
    local_currency: str | None = None,
    budget: float | None = None,
    cost_assumptions: dict[str, Any] | None = None,
    buyer_vat_registered: bool | None = None,
    commodity_code: str | None = None,
    origin_country: str | None = None,
    location: str | None = None,
    country_code: str | None = None,
) -> dict[str, Any] | None:
    """
    qty × tier unit + duty band + freight band → mid estimate + low–high range.
    States weight, freight rate, duty rate, and MOQ assumptions explicitly.
    Pass cost_assumptions from the same run so agents + calculator share rates.
    buyer_vat_registered: when True, omit VAT/sales tax from mid landed (B2B).
    """
    if not listing or not isinstance(listing, dict):
        return None
    # Never compute primary landed totals from unreliable / implausible scrapes
    if (
        listing.get("price_outlier")
        or listing.get("unit_price_unreliable")
        or listing.get("implausible_metal")
        or listing.get("unit_price_rejected")
    ):
        return None
    qty = int(quantity) if isinstance(quantity, int) and quantity > 0 else None
    if qty is None:
        return None

    # Tier gate: only PAGE-verified reliable tiers may replace the card unit price.
    # Snippet/SERP tiers (e.g. "Rs 3 after 100+") stay as an unconfirmed side note.
    work = dict(listing)
    tiers_verified = _tiers_are_verified(work)
    raw_tiers = work.get("price_tiers") if isinstance(work.get("price_tiers"), list) else []
    sel = select_tier_for_quantity(raw_tiers if tiers_verified else [], qty)
    moq_not_met = bool(sel.get("moq_not_met")) if tiers_verified else False
    tiers_reliable = bool(sel.get("tiers_reliable", True)) if tiers_verified else False

    unconfirmed_tier_note = None
    if raw_tiers and not tiers_verified:
        # Preserve snippet tier as labeled caveat only — never as primary unit
        work["price_tiers"] = None
        bits = []
        for t in raw_tiers[:3]:
            if isinstance(t, dict) and t.get("unit_price"):
                bits.append(f"{t.get('min_qty')}+ @ {t.get('unit_price')}")
        src = str(listing.get("tiers_source") or "snippet")
        unconfirmed_tier_note = (
            f"Unconfirmed possible tier ({src}, not used in primary total): "
            + (", ".join(bits) if bits else "see listing")
            + " — verify on seller page before relying on it."
        )
    elif moq_not_met:
        work["price_tiers"] = None
    elif not tiers_reliable:
        work["price_tiers"] = None
        unconfirmed_tier_note = (
            "Unconfirmed possible tier range (tiers unreliable) — not used as primary unit; "
            "verify on seller page."
        )
    elif sel.get("tier"):
        t = sel["tier"]
        work["price"] = t.get("unit_price") or work.get("price")
        work["price_source"] = "tier_selected"
        if t.get("currency"):
            work["currency"] = t.get("currency")

    unit_amt, unit_cur, tier_moq, tier_label = _pick_tier(
        work, qty, allow_tiers=tiers_verified and tiers_reliable and not moq_not_met
    )
    if unit_amt <= 0:
        return None

    # Primary range = verified unit × duty/freight band only (NOT unverified tier lows)
    unit_low_amt = unit_amt
    unit_high_amt = unit_amt
    if moq_not_met:
        tier_label = f"MOQ not met (need ≥{sel.get('lowest_min_qty')})"
    elif unconfirmed_tier_note:
        tier_label = f"{tier_label}; unverified tiers ignored for primary"

    local = (local_currency or "USD").upper()
    if local.lower().startswith("local"):
        local = "USD"

    profile = get_profile(
        location=location, country_code=country_code, currency=local
    )
    fx_trail: list = []
    unit_local = _to_local(
        unit_amt, unit_cur, local, fx_meta_out=fx_trail, profile=profile
    )
    if unit_local is None:
        return None
    unit_local_low = (
        _to_local(
            unit_low_amt, unit_cur, local, fx_meta_out=fx_trail, profile=profile
        )
        or unit_local
    )
    unit_local_high = (
        _to_local(
            unit_high_amt, unit_cur, local, fx_meta_out=fx_trail, profile=profile
        )
        or unit_local
    )

    line_local = unit_local * qty
    line_low = unit_local_low * qty
    line_high = unit_local_high * qty

    # Always rebuild assumptions for THIS listing (origin vs destination) — never reuse
    # a pool-wide foreign_factory bundle that would apply import duty to domestic rows.
    origin = infer_listing_origin(listing, profile, origin_country=origin_country)
    duty_bundle = shared_cost_assumptions(
        local_currency=local,
        location=location,
        country_code=country_code,
        commodity_code=commodity_code,
        origin_country=origin,
        buyer_vat_registered=buyer_vat_registered,
        profile=profile,
        listing=listing,
    )
    # Optional caller bundle may only supply commodity/label metadata — never override rates
    if isinstance(cost_assumptions, dict) and cost_assumptions.get("prompt_block_extra"):
        duty_bundle = {
            **duty_bundle,
            "prompt_block": duty_bundle.get("prompt_block", "")
            + str(cost_assumptions.get("prompt_block_extra") or ""),
        }

    foreign = bool(duty_bundle.get("is_import"))
    duty_mid = float(duty_bundle["duty_rate_mid"])
    duty_low = float(duty_bundle["duty_rate_low"])
    duty_high = float(duty_bundle["duty_rate_high"])
    tax_rate = float(duty_bundle["sales_tax_rate"])  # import VAT only
    domestic_vat_rate = float(duty_bundle.get("domestic_vat_rate") or 0.0)
    domestic_vat_in_mid = bool(duty_bundle.get("domestic_vat_in_mid"))

    weight_info = resolve_unit_weight_kg(listing, foreign=foreign)
    weight_f = weight_info.get("kg")
    weight_from_page = bool(weight_info.get("from_page"))
    weight_ignored = bool(weight_info.get("ignored"))
    weight_src = (
        "page"
        if weight_from_page
        else (
            "ignored_page"
            if weight_ignored
            else str(listing.get("package_weight_source") or "assumed").lower()
        )
    )

    ship_band, ship_meta = _shipping_band(
        foreign=foreign,
        qty=qty,
        weight_kg_unit=weight_f,
        weight_from_page=weight_from_page,
        local=local,
        freight_usd_per_kg={
            "low": float(duty_bundle["freight_usd_per_kg_low"]),
            "mid": float(duty_bundle["freight_usd_per_kg_mid"]),
            "high": float(duty_bundle["freight_usd_per_kg_high"]),
        }
        if foreign
        else None,
    )

    # Local delivery / MOV from page facts when present
    delivery_fee = 0.0
    try:
        if listing.get("delivery_fee") is not None:
            delivery_fee = float(listing["delivery_fee"])
        elif listing.get("local_delivery"):
            delivery_fee = float(parse_money(listing["local_delivery"]) or 0)
    except (TypeError, ValueError):
        delivery_fee = 0.0

    def total_for(line: float, duty_rate: float, ship: float) -> tuple[float, float, float, float]:
        """
        UK-style CIF duty: duty_base = goods + freight (+ insurance when known; none today).
        VAT base = goods + freight + duty. Returns (landed, duty_amt, duty_base, vat_base).
        """
        duty_base = line + ship  # CIF (insurance omitted until we have a sourced line)
        duty_amt = duty_base * duty_rate
        vat_base = line + ship + duty_amt
        import_vat = vat_base * tax_rate
        # Domestic VAT is a separate line — included in mid only when not reclaimable
        domestic_vat = (line * domestic_vat_rate) if domestic_vat_in_mid else 0.0
        landed = line + ship + duty_amt + import_vat + domestic_vat + delivery_fee
        return landed, duty_amt, duty_base, vat_base

    raw_low, _, _, _ = total_for(line_low, duty_low, ship_band["low"])
    raw_mid, duty_amt_mid, duty_base_mid, vat_base_mid = total_for(
        line_local, duty_mid, ship_band["mid"]
    )
    raw_high, _, _, _ = total_for(line_high, duty_high, ship_band["high"])
    domestic_vat_amount = line_local * domestic_vat_rate if domestic_vat_rate else 0.0
    # Min/max of the three assumption paths; mid = mid-assumption if inside, else midpoint
    total_low = min(raw_low, raw_mid, raw_high)
    total_high = max(raw_low, raw_mid, raw_high)
    if total_low <= raw_mid <= total_high:
        total_mid = raw_mid
    else:
        total_mid = (total_low + total_high) / 2.0
    assert total_low <= total_mid <= total_high

    freight_share = (ship_band["mid"] / total_mid) if total_mid > 0 else 0.0
    landed_goods_multiple = (
        (total_mid / line_local) if line_local and line_local > 0 else None
    )
    # Visible warning whenever landed is >3× goods (regardless of weight source)
    freight_dominates = bool(
        landed_goods_multiple is not None and landed_goods_multiple > 3.0
    )

    moq_raw = listing.get("moq")
    try:
        moq_n = int(moq_raw) if moq_raw is not None else tier_moq
    except (TypeError, ValueError):
        moq_n = tier_moq
    moq_source = str(listing.get("moq_source") or ("tier" if tier_moq else "not_verified"))
    # Placeholder / missing-source MOQs must not display as a confirmed number
    moq_unconfirmed = moq_source.lower() in (
        "not_on_snippet",
        "not_verified",
        "assumed_1_from_page_price",
        "missing",
        "",
    ) or (
        moq_n is not None
        and moq_source.lower().startswith("not_")
    )
    if moq_unconfirmed:
        moq_n = None
        moq_assumption = "MOQ not confirmed — verify on seller page"
        moq_ok = False
    else:
        moq_ok = moq_n is not None and moq_n > 0
        moq_assumption = (
            f"MOQ {moq_n} (source={moq_source})"
            if moq_ok
            else "MOQ not confirmed — verify on seller page"
        )
        if moq_ok and qty < moq_n:
            moq_assumption += f"; your qty {qty} is below MOQ {moq_n}"

    unit_disp = _fmt(unit_amt, unit_cur)
    line_disp = _fmt(line_local, local)
    duty_disp = _fmt(duty_amt_mid, local)
    duty_base_disp = _fmt(duty_base_mid, local)
    vat_base_disp = _fmt(vat_base_mid, local) if foreign else None
    ship_disp = _fmt(ship_band["mid"], local)
    total_disp = _fmt(total_mid, local)
    range_low_disp = _fmt(total_low, local)
    range_high_disp = _fmt(total_high, local)
    domestic_vat_disp = _fmt(domestic_vat_amount, local) if domestic_vat_rate else None
    duty_meta = duty_bundle.get("duty_meta") if isinstance(duty_bundle.get("duty_meta"), dict) else {}
    duty_fallback_visible = bool(duty_meta.get("used_fallback")) and foreign
    fx_meta_primary = fx_trail[-1] if fx_trail else None
    fx_fallback_visible = bool(
        isinstance(fx_meta_primary, dict) and fx_meta_primary.get("used_fallback")
    )

    # Single unambiguous formula — never show a pre-duty line total with "=" that
    # readers confuse for the mid landed figure.
    formula = (
        f"Mid landed: {total_disp} "
        f"({qty} × {unit_disp} [{tier_label}]"
        + (f" + freight ({ship_disp})" if ship_band["mid"] else " + freight 0")
        + (
            f" + duty {int(duty_mid * 100)}% on CIF duty base {duty_base_disp} ({duty_disp})"
            + (" [estimated, not a tariff lookup]" if duty_fallback_visible else "")
            if duty_mid
            else " + duty 0%"
        )
        + (
            f" + import VAT {int(tax_rate * 100)}% on {vat_base_disp}"
            if tax_rate and vat_base_disp
            else (f" + import VAT {int(tax_rate * 100)}%" if tax_rate else "")
        )
        + (
            f" + domestic VAT {int(domestic_vat_rate * 100)}% ({domestic_vat_disp})"
            if domestic_vat_in_mid and domestic_vat_rate
            else (
                f" + domestic VAT {int(domestic_vat_rate * 100)}% ({domestic_vat_disp}, reclaimable — excluded from mid)"
                if domestic_vat_rate and duty_bundle.get("buyer_vat_registered")
                else ""
            )
        )
        + (f" + delivery {_fmt(delivery_fee, local)}" if delivery_fee else "")
        + (
            " [FX: static fallback, not a live rate]"
            if fx_fallback_visible
            else ""
        )
        + f"). Range: {range_low_disp} – {range_high_disp}."
    )
    # Guard: display strings must agree with ordered amounts
    if not (total_low <= total_mid <= total_high):
        total_mid = (total_low + total_high) / 2.0
        total_disp = _fmt(total_mid, local)
        formula = (
            f"Mid landed: {total_disp}. Range: {range_low_disp} – {range_high_disp}."
        )

    if weight_ignored:
        weight_disp = (
            f"{weight_f} kg/unit (assumed) — page weight ignored "
            f"(looked like carton/gross weight); raw={weight_info.get('raw')!r}"
            if weight_f
            else (
                "page weight ignored (looked like carton/gross weight); "
                f"raw={weight_info.get('raw')!r}"
            )
        )
    elif weight_f and weight_from_page:
        weight_disp = f"{weight_f} kg/unit (page)"
    elif weight_f:
        weight_disp = f"{weight_f} kg/unit (assumed — not confirmed on page)"
    else:
        weight_disp = "Weight not confirmed — verify on seller page"
    freight_disp = (
        f"${float(duty_bundle['freight_usd_per_kg_mid']):.0f}/kg mid "
        f"(${float(duty_bundle['freight_usd_per_kg_low']):.0f}–"
        f"${float(duty_bundle['freight_usd_per_kg_high']):.0f})"
        if foreign and ship_meta.get("method") == "weight_x_freight"
        else ship_meta.get("freight_assumption", "n/a")
    )
    # Explicit derivation line for brief/table (weight × rate → freight amount)
    if foreign and ship_meta.get("method") == "weight_x_freight" and weight_f:
        total_kg = float(ship_meta.get("total_kg") or (weight_f * qty))
        freight_derivation = (
            f"Freight derivation: {weight_disp} × qty {qty} = {total_kg:g} kg × "
            f"${float(duty_bundle['freight_usd_per_kg_mid']):.0f}/kg mid "
            f"→ {ship_disp} (FX USD→{local}"
            + (
                "; static FX fallback, not a live rate"
                if fx_fallback_visible
                else ""
            )
            + ")"
        )
    elif foreign:
        freight_derivation = (
            f"Freight derivation: {ship_meta.get('freight_assumption') or freight_disp}"
            f" → {ship_disp}"
        )
    else:
        freight_derivation = "Freight derivation: 0 (domestic)"

    duty_assumption = (
        (
            f"Duty: {int(duty_mid * 100)}% mid on CIF duty base {duty_base_disp} "
            f"(goods {line_disp} + freight {ship_disp}) "
            f"({int(duty_low * 100)}–{int(duty_high * 100)}% band) — "
            f"{duty_meta.get('label') or 'assumption, not official customs'}"
            + (" — estimated, not a tariff lookup" if duty_fallback_visible else "")
            + f" [as of {duty_meta.get('effective_date') or 'n/a'}]"
        )
        if foreign
        else "Duty: 0% (domestic listing)"
    )
    fx_assumption = None
    if fx_fallback_visible:
        fx_assumption = (
            "FX: static fallback rate, not a live rate "
            "(estimated, not a live FX quote)"
        )
    elif isinstance(fx_meta_primary, dict) and fx_meta_primary.get("source") == "same_currency":
        fx_assumption = f"FX: same currency ({unit_cur})"
    elif isinstance(fx_meta_primary, dict):
        fr = fx_meta_primary.get("from") if isinstance(fx_meta_primary.get("from"), dict) else {}
        to = fx_meta_primary.get("to") if isinstance(fx_meta_primary.get("to"), dict) else {}
        fx_assumption = (
            f"FX: {unit_cur}→{local} via live quote "
            f"(as of {fr.get('as_of') or to.get('as_of') or 'n/a'}; "
            f"source {fr.get('source') or to.get('source') or fx_meta_primary.get('source')})"
        )

    assumptions = [
        f"Weight: {weight_disp}",
        f"Freight: {freight_disp} (share {int(freight_share * 100)}% of mid total)",
        freight_derivation,
        duty_assumption,
        (
            f"Import VAT: {int(tax_rate * 100)}% on goods+freight+duty ({vat_base_disp})"
            + (
                " (buyer VAT-registered — omitted)"
                if duty_bundle.get("buyer_vat_registered") and foreign
                else ""
            )
            + f" — {(duty_bundle.get('sales_tax_meta') or {}).get('label') or 'assumption'}"
            if foreign and (tax_rate or duty_bundle.get("buyer_vat_registered"))
            else (
                f"Domestic VAT: {int(domestic_vat_rate * 100)}% ({domestic_vat_disp})"
                + (
                    " — reclaimable, excluded from mid (buyer VAT-registered)"
                    if duty_bundle.get("buyer_vat_registered")
                    else " — included in mid as a separate line"
                )
                if domestic_vat_rate
                else "Sales tax / VAT: 0% (not applied)"
            )
        ),
        f"Origin: {origin} ({'import' if foreign else 'domestic'})",
        f"MOQ: {moq_assumption}",
        (
            "Primary unit from listing card / page-verified tier only."
            if tiers_verified and tiers_reliable
            else "Primary unit from listing card — snippet/unverified tiers not applied."
        ),
    ]
    if fx_assumption:
        assumptions.insert(3, fx_assumption)
    if unconfirmed_tier_note:
        assumptions.append(unconfirmed_tier_note)
    if moq_not_met:
        assumptions.append(
            f"MOQ not met: order qty {qty} < tier min {sel.get('lowest_min_qty')} — tier price not applied."
        )
    if freight_dominates:
        assumptions.append(
            f"Warning: landed/goods ≈ {landed_goods_multiple:.1f}× (>3×) — "
            "freight/weight or duty assumptions dominate; verify package weight and tiers."
        )
    if weight_ignored:
        assumptions.append(
            str(weight_info.get("ignore_reason") or "")
            + (f" — {weight_info.get('how')}" if weight_info.get("how") else "")
        )
    # Always surface how raw weight became per-unit (smoke / brief audit)
    if weight_info.get("how"):
        assumptions.append(f"Weight parse: {weight_info.get('how')}")
    assumptions.append(
        f"Price tier used: {unit_disp} ({tier_label})"
        + (f"; applies at qty ≥ {tier_moq}" if tier_moq else f"; order qty {qty}")
    )
    if budget is None:
        assumptions.append("No budget set — cannot compute over/under or max units that fit.")
    if delivery_fee:
        assumptions.append(f"Local delivery fee included: {_fmt(delivery_fee, local)}")

    # Whether Buy vs Skip would flip across the range given a budget
    flips = False
    budget_disp = None
    cost_vs_budget = None
    fits_budget_mid = None
    fits_budget_low = None
    max_units = None
    max_units_note = None
    if budget is not None:
        try:
            b = float(budget)
            if b > 0:
                budget_disp = _fmt(b, local)
                under_low = total_low <= b
                under_high = total_high <= b
                flips = under_low != under_high
                fits_budget_mid = total_mid <= b
                fits_budget_low = total_low <= b
                delta = b - total_mid
                if fits_budget_mid:
                    cost_vs_budget = f"Mid landed {total_disp} is under budget {budget_disp} (headroom {_fmt(delta, local)})"
                else:
                    cost_vs_budget = f"Mid landed {total_disp} is over budget {budget_disp} by {_fmt(abs(delta), local)}"
                # Max units that fit: budget / per-unit mid landed (duty+freight scaled)
                per_unit_mid = total_mid / qty if qty else 0
                if per_unit_mid > 0:
                    raw_max = int(b // per_unit_mid)
                    if moq_ok and moq_n and raw_max > 0 and raw_max < moq_n:
                        max_units = 0
                        max_units_note = (
                            f"Budget fits ~{raw_max} unit(s) at mid landed, but MOQ is {moq_n}"
                        )
                    else:
                        max_units = max(0, raw_max)
                        max_units_note = (
                            f"At mid landed ~{_fmt(per_unit_mid, local)}/unit, "
                            f"budget {budget_disp} covers about {max_units} unit(s)"
                            + (f" (MOQ {moq_n})" if moq_ok else "")
                        )
        except (TypeError, ValueError):
            flips = False

    if cost_vs_budget:
        assumptions.append(cost_vs_budget)
    if max_units_note:
        assumptions.append(max_units_note)

    return {
        "quantity": qty,
        "tier_label": tier_label,
        "tier_min_qty": tier_moq,
        "moq": moq_n,
        "moq_assumption": moq_assumption,
        "moq_source": moq_source,
        "unit_price": unit_disp,
        "unit_price_raw": str(listing.get("price") or ""),
        "unit_price_parsed_currency": unit_cur,
        "unit_price_source": str(listing.get("price_source") or tier_label),
        "unit_price_local": _fmt(unit_local, local),
        "line_total": line_disp,
        "goods_amount": round(line_local, 2),
        "duty_rate": duty_mid,
        "duty_rate_low": duty_low,
        "duty_rate_high": duty_high,
        "duty_assumption": duty_assumption,
        "duty_base": duty_base_disp,
        "duty_base_amount": round(duty_base_mid, 2),
        "duty_amount": duty_disp,
        "duty_amount_value": round(duty_amt_mid, 2),
        "vat_base": vat_base_disp,
        "vat_base_amount": round(vat_base_mid, 2) if foreign else 0.0,
        "duty_fallback": duty_fallback_visible,
        "duty_fallback_label": "estimated, not a tariff lookup" if duty_fallback_visible else None,
        "fx_fallback": fx_fallback_visible,
        "fx_fallback_label": (
            "estimated, not a live FX quote" if fx_fallback_visible else None
        ),
        "freight_derivation": freight_derivation,
        "origin_country": origin,
        "is_import": foreign,
        "domestic_vat_rate": domestic_vat_rate,
        "domestic_vat_amount": round(domestic_vat_amount, 2),
        "domestic_vat_display": domestic_vat_disp,
        "domestic_vat_in_mid": domestic_vat_in_mid,
        "domestic_vat_reclaimable": bool(
            domestic_vat_rate and duty_bundle.get("buyer_vat_registered")
        ),
        "package_weight_kg": weight_f,
        "package_weight_raw": weight_info.get("raw"),
        "package_weight_basis": weight_info.get("basis"),
        "package_weight_pcs_per_carton": weight_info.get("pcs_per_carton"),
        "package_weight_kg_as_parsed": weight_info.get("kg_as_parsed"),
        "weight_from_page": weight_from_page,
        "weight_ignored": weight_ignored,
        "weight_ignore_reason": weight_info.get("ignore_reason"),
        "weight_how": weight_info.get("how"),
        "weight_assumption": weight_disp,
        "landed_goods_multiple": (
            round(landed_goods_multiple, 3) if landed_goods_multiple is not None else None
        ),
        "price_tier_label": tier_label,
        "price_tier_min_qty": tier_moq,
        "price_tier_unit": unit_disp,
        "price_card_raw": str(listing.get("price") or ""),
        "freight_rate": float(duty_bundle["freight_usd_per_kg_mid"]) if foreign else 0.0,
        "freight_rate_low": float(duty_bundle["freight_usd_per_kg_low"]) if foreign else 0.0,
        "freight_rate_high": float(duty_bundle["freight_usd_per_kg_high"]) if foreign else 0.0,
        "cost_assumptions_label": duty_bundle.get("label"),
        "freight_assumption": ship_meta.get("freight_assumption"),
        "shipping_assumption": ship_meta.get("freight_assumption"),
        "shipping_amount": ship_disp,
        "estimated_total": total_disp,
        "range_low": range_low_disp,
        "range_high": range_high_disp,
        "range_low_amount": round(total_low, 2),
        "range_high_amount": round(total_high, 2),
        "estimated_total_amount": round(total_mid, 2),
        "verdict_flips_in_range": flips,
        "budget_amount": budget,
        "budget_display": budget_disp,
        "cost_vs_budget": cost_vs_budget,
        "fits_budget_mid": fits_budget_mid,
        "fits_budget_low": fits_budget_low,
        "max_units_that_fit": max_units,
        "max_units_note": max_units_note,
        "moq_not_met": moq_not_met,
        "tiers_reliable": bool(tiers_verified and tiers_reliable),
        "tiers_verified": tiers_verified,
        "unconfirmed_tier_note": unconfirmed_tier_note,
        "freight_share": round(freight_share, 3),
        "freight_dominates_warning": freight_dominates,
        "sales_tax_rate": tax_rate,
        "buyer_vat_registered": bool(duty_bundle.get("buyer_vat_registered")),
        "duty_meta": duty_bundle.get("duty_meta"),
        "sales_tax_meta": duty_bundle.get("sales_tax_meta"),
        "freight_meta": duty_bundle.get("freight_meta"),
        "fx_meta": fx_meta_primary,
        "profile_id": duty_bundle.get("profile_id"),
        "trade_zone": duty_bundle.get("trade_zone"),
        "delivery_fee": delivery_fee,
        "unit_basis": listing.get("unit_basis") or "per_piece",
        "currency": local,
        "formula": formula,
        "assumptions": assumptions,
        "listing_link": str(listing.get("link") or ""),
        "listing_title": str(listing.get("title") or ""),
    }
