"""Shared landed-cost assumptions — RegionProfile is the source of truth.

Built per listing (origin vs destination). Flat duty_rate_mid remains only as a
labeled fallback when HS/origin lookup misses. Every duty/tax/freight value
carries effective_date + source_url.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.region_profile import get_profile, import_origin_group, lookup_duty

# ---- Legacy maps (derived from profiles for callers that still index by currency) ----


def _legacy_from_profiles() -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    sales: dict[str, float] = {"USD": 0.0}
    duty: dict[str, float] = {"USD": 0.08}
    flat: dict[str, float] = {"USD": 55}
    for pid in ("pk", "uk"):
        try:
            from app.core.region_profile import load_profile

            p = load_profile(pid)
        except Exception:
            continue
        cur = str(p.get("currency") or "").upper()
        if not cur:
            continue
        st = p.get("sales_tax") if isinstance(p.get("sales_tax"), dict) else {}
        sales[cur] = float(st.get("rate") or 0)
        fb = (p.get("duty") or {}).get("fallback") if isinstance(p.get("duty"), dict) else {}
        duty[cur] = float((fb or {}).get("rate_mid") or 0.15)
        ship = p.get("shipping_flat_local") if isinstance(p.get("shipping_flat_local"), dict) else {}
        if ship.get("amount") is not None:
            flat[cur] = float(ship["amount"])
    sales.setdefault("INR", 0.18)
    sales.setdefault("AED", 0.05)
    sales.setdefault("SAR", 0.15)
    sales.setdefault("EUR", 0.20)
    sales.setdefault("CAD", 0.13)
    sales.setdefault("AUD", 0.10)
    sales.setdefault("SGD", 0.09)
    duty.setdefault("INR", 0.20)
    duty.setdefault("AED", 0.05)
    duty.setdefault("SAR", 0.15)
    duty.setdefault("EUR", 0.12)
    duty.setdefault("CAD", 0.10)
    duty.setdefault("AUD", 0.10)
    duty.setdefault("SGD", 0.07)
    flat.setdefault("INR", 4500)
    flat.setdefault("AED", 120)
    flat.setdefault("SAR", 180)
    flat.setdefault("EUR", 50)
    flat.setdefault("CAD", 70)
    flat.setdefault("AUD", 75)
    flat.setdefault("SGD", 40)
    return sales, duty, flat


SALES_TAX_BY_CURRENCY, DUTY_RATE_BY_CURRENCY, SHIPPING_FLAT_BY_CURRENCY = _legacy_from_profiles()

FREIGHT_USD_PER_KG = {"low": 6.0, "mid": 10.0, "high": 16.0}

_FALLBACK_DUTY_VISIBLE = "estimated, not a tariff lookup"


def infer_listing_origin(
    listing: dict[str, Any] | None,
    profile: dict[str, Any],
    *,
    origin_country: str | None = None,
) -> str:
    """Best-effort ISO-ish origin code for duty / import-group checks."""
    if origin_country and str(origin_country).strip():
        return str(origin_country).strip().upper()
    if not listing or not isinstance(listing, dict):
        return "ROW"
    raw = str(listing.get("supplier_origin") or "").strip().upper()
    if raw and raw not in ("FOREIGN", "LOCAL", "UNKNOWN"):
        return raw
    link = str(listing.get("link") or "")
    if re.search(
        r"alibaba\.|made-in-china\.|dhgate\.|globalsources\.|aliexpress\.|1688\.",
        link,
        re.I,
    ):
        return "CN"
    if re.search(r"indiamart\.|tradeindia\.", link, re.I):
        return "IN"
    if re.search(r"faire\.com|ebay\.co\.uk|amazon\.co\.uk|\.co\.uk(/|$)", link, re.I):
        # UK marketplace host — treat as UK origin unless flagged otherwise
        if str(profile.get("country_code") or "").lower() in ("uk", "gb"):
            return "UK"
    if re.search(r"faire\.com|ebay\.com|amazon\.com(?!\.)", link, re.I):
        if str(profile.get("country_code") or "").lower() in ("us",):
            return "US"
    # Default: first domestic code for this destination
    groups = profile.get("import_origin_groups") if isinstance(profile.get("import_origin_groups"), dict) else {}
    domestic = groups.get("domestic") or []
    if domestic:
        return str(domestic[0]).upper()
    return str(profile.get("country_code") or "ROW").upper()


def shared_cost_assumptions(
    *,
    local_currency: str | None = None,
    foreign_factory: bool | None = None,
    location: str | None = None,
    country_code: str | None = None,
    commodity_code: str | None = None,
    origin_country: str | None = None,
    buyer_vat_registered: bool | None = None,
    profile: dict[str, Any] | None = None,
    listing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Deterministic duty / freight / tax band for ONE listing (origin vs destination).
    Agents must cite ONLY these rates — never invent 20%+5% alternatives.
    """
    prof = profile or get_profile(
        location=location, country_code=country_code, currency=local_currency
    )
    local = (local_currency or prof.get("currency") or "USD").upper()
    if local.lower().startswith("local"):
        local = str(prof.get("currency") or "USD").upper()

    origin = infer_listing_origin(listing, prof, origin_country=origin_country)
    group = import_origin_group(prof, origin)
    is_import = group != "domestic"
    # Legacy callers may still pass foreign_factory; prefer origin group when listing/origin given
    if foreign_factory is not None and listing is None and origin_country is None:
        is_import = bool(foreign_factory)

    freight = prof.get("freight_usd_per_kg") if isinstance(prof.get("freight_usd_per_kg"), dict) else {}
    fl = float(freight.get("low", FREIGHT_USD_PER_KG["low"]))
    fm = float(freight.get("mid", FREIGHT_USD_PER_KG["mid"]))
    fh = float(freight.get("high", FREIGHT_USD_PER_KG["high"]))
    freight_meta = {
        "low": fl,
        "mid": fm,
        "high": fh,
        "effective_date": freight.get("effective_date"),
        "source_url": freight.get("source_url"),
        "label": freight.get("label"),
    }

    sales = prof.get("sales_tax") if isinstance(prof.get("sales_tax"), dict) else {}
    tax_full = float(sales.get("rate") or 0.0)
    vat_reg = bool(buyer_vat_registered)
    tax_meta_base = {
        "rate_if_not_registered": tax_full,
        "buyer_vat_registered": vat_reg,
        "effective_date": sales.get("effective_date"),
        "source_url": sales.get("source_url"),
        "label": sales.get("label"),
    }

    if not is_import:
        # Domestic: duty 0, import VAT 0; domestic VAT is a separate reclaimable line
        domestic_vat_rate = tax_full
        domestic_vat_in_mid = (not vat_reg) and domestic_vat_rate > 0
        tax_meta = {
            **tax_meta_base,
            "rate": 0.0,  # import VAT not applied
            "kind": "domestic_vat",
            "domestic_vat_rate": domestic_vat_rate,
            "domestic_vat_in_mid": domestic_vat_in_mid,
            "reclaimable": vat_reg,
            "label": (
                f"Domestic VAT/sales tax {int(domestic_vat_rate * 100)}%"
                + (" — reclaimable (buyer VAT-registered; excluded from mid)" if vat_reg else " — included in mid")
            ),
        }
        prompt_block = (
            "SHARED COST ASSUMPTIONS (use these exact figures; do not invent other duty %):\n"
            f"- Destination: {prof.get('display_name')} ({local}) trade_zone={prof.get('trade_zone')}\n"
            f"- Listing origin: {origin} (domestic) — duty 0%, inbound freight 0%, import VAT 0%\n"
            f"- Domestic VAT/sales tax: {int(domestic_vat_rate * 100)}%"
            + (
                " (buyer VAT-registered — shown as reclaimable, excluded from mid landed)"
                if vat_reg
                else " (included in mid landed as a separate domestic VAT line)"
            )
            + f" [as of {tax_meta.get('effective_date') or 'n/a'}]\n"
            "If you mention duty or freight, cite ONLY these rates.\n"
        )
        return {
            "currency": local,
            "profile_id": prof.get("id"),
            "trade_zone": prof.get("trade_zone"),
            "foreign_factory": False,
            "is_import": False,
            "origin_country": origin,
            "import_origin_group": "domestic",
            "duty_rate_mid": 0.0,
            "duty_rate_low": 0.0,
            "duty_rate_high": 0.0,
            "duty_meta": {
                "matched": False,
                "used_fallback": False,
                "label": "domestic listing — duty not applied",
                "effective_date": None,
                "source_url": None,
            },
            "sales_tax_rate": 0.0,
            "sales_tax_meta": tax_meta,
            "domestic_vat_rate": domestic_vat_rate,
            "domestic_vat_in_mid": domestic_vat_in_mid,
            "freight_usd_per_kg_low": 0.0,
            "freight_usd_per_kg_mid": 0.0,
            "freight_usd_per_kg_high": 0.0,
            "freight_meta": {**freight_meta, "low": 0.0, "mid": 0.0, "high": 0.0},
            "buyer_vat_registered": vat_reg,
            "label": (
                f"domestic — duty 0%, domestic VAT {int(domestic_vat_rate * 100)}%"
                + (" (reclaimable)" if vat_reg else "")
            ),
            "prompt_block": prompt_block,
        }

    duty_row = lookup_duty(
        prof, commodity_code=commodity_code, origin_country=origin
    )
    duty_mid = float(duty_row.get("rate_mid") or DUTY_RATE_BY_CURRENCY.get(local, 0.15))
    duty_low = float(
        duty_row["rate_low"]
        if duty_row.get("rate_low") is not None
        else max(0.0, duty_mid - 0.10)
    )
    duty_high = float(
        duty_row["rate_high"]
        if duty_row.get("rate_high") is not None
        else min(0.45, duty_mid + 0.10)
    )
    used_fallback = bool(duty_row.get("used_fallback") or not duty_row.get("matched"))
    duty_label = duty_row.get("label") or ""
    if used_fallback and _FALLBACK_DUTY_VISIBLE not in str(duty_label).lower():
        duty_label = f"{duty_label} — {_FALLBACK_DUTY_VISIBLE}".strip(" —")
    duty_meta = {
        "matched": bool(duty_row.get("matched")),
        "used_fallback": used_fallback,
        "label": duty_label,
        "visible_label": _FALLBACK_DUTY_VISIBLE if used_fallback else None,
        "effective_date": duty_row.get("effective_date"),
        "source_url": duty_row.get("source_url"),
        "commodity_code": commodity_code or "*",
        "origin_country": origin,
        "destination": prof.get("country_code"),
    }

    # Import VAT on CIF+duty+freight — omitted from mid when buyer VAT-registered
    import_vat = 0.0 if vat_reg else tax_full
    tax_meta = {
        **tax_meta_base,
        "rate": import_vat,
        "kind": "import_vat",
        "domestic_vat_rate": 0.0,
        "domestic_vat_in_mid": False,
        "reclaimable": vat_reg,
    }

    fallback_note = (
        f" — {_FALLBACK_DUTY_VISIBLE}"
        if used_fallback
        else ""
    )
    prompt_block = (
        "SHARED COST ASSUMPTIONS (use these exact figures; do not invent other duty %):\n"
        f"- Destination: {prof.get('display_name')} ({local}) trade_zone={prof.get('trade_zone')}\n"
        f"- Listing origin: {origin} (import)\n"
        f"- Duty mid: {int(duty_mid * 100)}% "
        f"(band {int(duty_low * 100)}–{int(duty_high * 100)}%) — "
        f"{'HS/origin lookup' if duty_meta['matched'] else 'labeled flat fallback'}"
        f"{fallback_note}"
        f" [as of {duty_meta.get('effective_date') or 'n/a'}]\n"
        f"- Import VAT/sales tax: {int(import_vat * 100)}%"
        + (
            f" (buyer VAT-registered — tax omitted from mid landed; full rate would be {int(tax_full * 100)}%)"
            if vat_reg
            else ""
        )
        + f" [as of {tax_meta.get('effective_date') or 'n/a'}]\n"
        f"- Air freight: ${fl:.0f}–${fh:.0f}/kg (mid ${fm:.0f}/kg)"
        f" [as of {freight_meta.get('effective_date') or 'n/a'}]\n"
        "If you mention duty or freight, cite ONLY these rates. "
        "Do NOT invent alternate schemes like '20% CIF + 5% surcharge'.\n"
    )
    return {
        "currency": local,
        "profile_id": prof.get("id"),
        "trade_zone": prof.get("trade_zone"),
        "foreign_factory": True,
        "is_import": True,
        "origin_country": origin,
        "import_origin_group": group,
        "duty_rate_mid": duty_mid,
        "duty_rate_low": duty_low,
        "duty_rate_high": duty_high,
        "duty_meta": duty_meta,
        "sales_tax_rate": import_vat,
        "sales_tax_meta": tax_meta,
        "domestic_vat_rate": 0.0,
        "domestic_vat_in_mid": False,
        "freight_usd_per_kg_low": fl,
        "freight_usd_per_kg_mid": fm,
        "freight_usd_per_kg_high": fh,
        "freight_meta": freight_meta,
        "buyer_vat_registered": vat_reg,
        "label": (
            f"import origin={origin} duty {int(duty_mid * 100)}% mid "
            f"({int(duty_low * 100)}–{int(duty_high * 100)}%), "
            f"freight ${fm:.0f}/kg mid, import VAT {int(import_vat * 100)}%"
            + (" (VAT-reg)" if vat_reg else "")
            + (f" [{_FALLBACK_DUTY_VISIBLE}]" if used_fallback else "")
        ),
        "prompt_block": prompt_block,
    }


def destination_prompt_block(
    *,
    profile: dict[str, Any],
    local_currency: str | None = None,
    buyer_vat_registered: bool | None = None,
) -> str:
    """Short destination-level note for agents (rates still computed per listing)."""
    local = (local_currency or profile.get("currency") or "").upper()
    fb = ((profile.get("duty") or {}).get("fallback") or {}) if isinstance(profile.get("duty"), dict) else {}
    st = profile.get("sales_tax") if isinstance(profile.get("sales_tax"), dict) else {}
    return (
        "DESTINATION COST FRAME (per-listing origin decides domestic vs import):\n"
        f"- Destination: {profile.get('display_name')} ({local}) trade_zone={profile.get('trade_zone')}\n"
        f"- Flat import duty fallback mid: {int(float(fb.get('rate_mid') or 0) * 100)}% "
        f"({_FALLBACK_DUTY_VISIBLE})\n"
        f"- Profile VAT/sales tax rate: {int(float(st.get('rate') or 0) * 100)}%"
        + (" (buyer VAT-registered — reclaimable / omitted from mid where applicable)" if buyer_vat_registered else "")
        + "\n"
        "- Domestic origin → duty 0%, import VAT 0%; domestic VAT shown as its own line.\n"
        "- Import origin (incl. EU→UK) → duty + freight + import VAT from the listing's assumptions.\n"
        "Cite ONLY the AUTHORITATIVE LANDED COST / per-listing figures in context.\n"
    )
