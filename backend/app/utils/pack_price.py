"""Detect pack/lot/carton pricing and normalize or flag."""
from __future__ import annotations

import re
from typing import Any

_PACK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:box|carton|case|pack|pkt|packet)\s*(?:of\s*)?(\d{1,5})\b", re.I), "box_of_n"),
    (re.compile(r"\b(\d{1,5})\s*(?:pcs?|pieces?|units?|pens?|bags?)\s*(?:\/|per\s*)?(?:box|carton|case|pack)\b", re.I), "n_per_box"),
    (re.compile(r"\b(\d{1,5})\s*(?:pc|pcs|pieces?)(?:lot|\/lot|\s+lot)\b", re.I), "n_pc_lot"),
    # "1000 Count" / "500 ct" / "200 count white disposable"
    (re.compile(r"\b(\d{2,5})\s*(?:count|ct|cnt)\b", re.I), "n_count"),
    (re.compile(r"\b(\d{2,5})\s*pcs?\b", re.I), "n_pcs"),  # e.g. 100pcs wholesale tote
    (re.compile(r"\b(?:per|/)\s*(?:box|carton|case|pack|pallet|lot)\b", re.I), "per_pack_word"),
    (re.compile(r"\b(?:per|/)\s*1000\b", re.I), "per_1000"),
    (re.compile(r"\b(?:pallet|lot|container)\s*(?:price|of)?\b", re.I), "lot_word"),
    (re.compile(r"\b(\d{2,5})\s*(?:-\s*)?(?:pack|pcslot|pcs\s*lot)\b", re.I), "n_pack"),
]


def _blobs(listing: dict[str, Any]) -> str:
    parts = [
        listing.get("title"),
        listing.get("snippet"),
        listing.get("pack_text"),
        listing.get("description"),
        listing.get("price"),
    ]
    return " ".join(str(p) for p in parts if p)


def detect_pack_pricing(listing: dict[str, Any] | None) -> dict[str, Any]:
    """
    Returns pack_units (int|None), pack_text, price_may_be_per_pack.
    When pack_units is known, caller may normalize unit = price / pack_units.
    When only 'per pack/lot/pallet' language without N, flag and hide landed.
    """
    if not listing or not isinstance(listing, dict):
        return {
            "pack_units": None,
            "pack_text": None,
            "price_may_be_per_pack": False,
            "pack_kind": None,
        }
    blob = _blobs(listing)
    if listing.get("pack_text"):
        blob = f"{listing.get('pack_text')} {blob}"

    for cre, kind in _PACK_PATTERNS:
        m = cre.search(blob)
        if not m:
            continue
        units = None
        if m.lastindex:
            try:
                units = int(str(m.group(1)).replace(",", ""))
            except (TypeError, ValueError):
                units = None
        if kind == "per_1000":
            units = 1000
        if kind in ("per_pack_word", "lot_word") and units is None:
            return {
                "pack_units": None,
                "pack_text": m.group(0),
                "price_may_be_per_pack": True,
                "pack_kind": kind,
            }
        if units and units > 1:
            return {
                "pack_units": units,
                "pack_text": m.group(0),
                "price_may_be_per_pack": True,
                "pack_kind": kind,
            }
    return {
        "pack_units": None,
        "pack_text": None,
        "price_may_be_per_pack": False,
        "pack_kind": None,
    }


def normalize_pack_unit_price(
    unit_amt: float,
    listing: dict[str, Any] | None,
) -> tuple[float, dict[str, Any]]:
    """Divide by pack_units when detected; otherwise flag-only meta."""
    meta = detect_pack_pricing(listing)
    if meta.get("pack_units") and meta["pack_units"] > 1 and unit_amt > 0:
        return unit_amt / float(meta["pack_units"]), {
            **meta,
            "normalized": True,
            "unit_before_pack": unit_amt,
        }
    return unit_amt, {**meta, "normalized": False}
