"""RegionProfile restricted_origins — warn + block Best pick, never silent drop."""
from __future__ import annotations

from typing import Any

from app.core.region_profile import get_profile


def _origin_code(listing: dict[str, Any]) -> str:
    for key in ("supplier_origin", "origin_country", "origin"):
        raw = str(listing.get(key) or "").strip().upper()
        if raw:
            return raw[:2] if len(raw) >= 2 else raw
    link = str(listing.get("link") or "").lower()
    if "indiamart." in link or "tradeindia." in link:
        return "IN"
    if "alibaba." in link or "dhgate." in link or "made-in-china." in link:
        return "CN"
    return ""


def annotate_restricted_origins(
    listings: list[dict[str, Any]] | None,
    *,
    location: str | None = None,
    country_code: str | None = None,
    local_currency: str | None = None,
) -> list[dict[str, Any]]:
    """
    Stamp origin_restricted + visible warning from profile.restricted_origins.
    Clears best_pick on flagged rows (no silent removal).
    """
    profile = get_profile(
        location=location, country_code=country_code, currency=local_currency
    )
    restricted = {
        str(x).strip().upper()
        for x in (profile.get("restricted_origins") or [])
        if str(x).strip()
    }
    warn = str(
        profile.get("restricted_origins_warning")
        or "This supplier origin may be restricted for your country — confirm trade rules before ordering."
    )
    out: list[dict[str, Any]] = []
    for row in listings or []:
        item = dict(row)
        origin = _origin_code(item)
        if origin and origin in restricted:
            item["origin_restricted"] = True
            item["origin_restricted_code"] = origin
            item["origin_restricted_warning"] = warn
            item["best_pick"] = False
            if item.get("pick_reason"):
                item.pop("pick_reason", None)
            # Surface in rank_reason for table / receipts
            prev = str(item.get("rank_reason") or "").strip()
            note = f"Restricted origin ({origin}): {warn}"
            item["rank_reason"] = f"{prev} · {note}".strip(" ·") if prev else note
        else:
            item.setdefault("origin_restricted", False)
        out.append(item)
    return out
