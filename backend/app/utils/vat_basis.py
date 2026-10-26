"""UK VAT basis for domestic landed cost (shelf vs trade / ex-VAT)."""
from __future__ import annotations

from typing import Any, Literal

VatBasis = Literal["includes_vat", "excludes_vat", "unknown"]


def infer_price_includes_vat(
    listing: dict[str, Any] | None,
    *,
    price_type: str | None = None,
) -> bool | None:
    """
    True  = consumer/retail shelf price already includes VAT
    False = trade/B2B quote excludes VAT
    None  = unknown (flag; math assumes includes_vat)
    """
    if not listing:
        return None
    pt = (price_type or listing.get("price_type") or "").strip().lower()
    if listing.get("price_includes_vat") is True:
        return True
    if listing.get("price_includes_vat") is False:
        return False
    if pt == "retail" or listing.get("uk_retail_priced") or listing.get("is_shopping_offer"):
        return True
    if pt in ("trade", "moq_tier"):
        return False
    if listing.get("wholesale") or listing.get("supplier_type") in (
        "factory",
        "wholesaler",
        "trading",
    ):
        return False
    return None


def vat_basis_label(includes: bool | None) -> VatBasis:
    if includes is True:
        return "includes_vat"
    if includes is False:
        return "excludes_vat"
    return "unknown"


def apply_domestic_vat_basis(
    goods_gross: float,
    *,
    vat_rate: float,
    buyer_vat_registered: bool,
    price_includes_vat: bool | None,
) -> dict[str, Any]:
    """
    Domestic path only. Returns mid goods line + VAT disclosure.

    includes VAT, not registered: cost = price as shown
    includes VAT, registered:     cost = price / (1+rate)
    excludes VAT, not registered: cost = price + VAT
    excludes VAT, registered:     cost = price (VAT reclaimable)
    unknown: treat as includes_vat + flag
    """
    rate = float(vat_rate or 0.0)
    basis = vat_basis_label(price_includes_vat)
    unknown = price_includes_vat is None
    includes = True if unknown else bool(price_includes_vat)
    vat_reg = bool(buyer_vat_registered)

    if rate <= 0:
        return {
            "goods_for_mid": round(goods_gross, 4),
            "domestic_vat_amount": 0.0,
            "domestic_vat_in_mid": False,
            "domestic_vat_reclaimable": False,
            "price_includes_vat": includes if not unknown else None,
            "vat_basis": basis,
            "vat_basis_unknown": unknown,
            "vat_basis_note": "no domestic VAT rate",
        }

    if includes:
        # Shelf price already has VAT embedded
        net = goods_gross / (1.0 + rate)
        vat_embedded = goods_gross - net
        if vat_reg:
            return {
                "goods_for_mid": round(net, 4),
                "domestic_vat_amount": round(vat_embedded, 4),
                "domestic_vat_in_mid": False,
                "domestic_vat_reclaimable": True,
                "price_includes_vat": True if not unknown else None,
                "vat_basis": basis,
                "vat_basis_unknown": unknown,
                "vat_basis_note": (
                    "shelf includes VAT; buyer VAT-registered → cost = price/1.2"
                    + (" (basis unknown — assumed includes)" if unknown else "")
                ),
            }
        return {
            "goods_for_mid": round(goods_gross, 4),
            "domestic_vat_amount": round(vat_embedded, 4),
            "domestic_vat_in_mid": False,  # already in shelf price — do not add again
            "domestic_vat_reclaimable": False,
            "price_includes_vat": True if not unknown else None,
            "vat_basis": basis,
            "vat_basis_unknown": unknown,
            "vat_basis_note": (
                "shelf includes VAT; buyer not registered → cost = price as shown"
                + (" (basis unknown — assumed includes)" if unknown else "")
            ),
        }

    # Excludes VAT (trade / B2B)
    vat_on_net = goods_gross * rate
    if vat_reg:
        return {
            "goods_for_mid": round(goods_gross, 4),
            "domestic_vat_amount": round(vat_on_net, 4),
            "domestic_vat_in_mid": False,
            "domestic_vat_reclaimable": True,
            "price_includes_vat": False,
            "vat_basis": "excludes_vat",
            "vat_basis_unknown": False,
            "vat_basis_note": "trade ex-VAT; buyer VAT-registered → net price, VAT reclaimable",
        }
    return {
        "goods_for_mid": round(goods_gross, 4),
        "domestic_vat_amount": round(vat_on_net, 4),
        "domestic_vat_in_mid": True,  # add 20% onto mid
        "domestic_vat_reclaimable": False,
        "price_includes_vat": False,
        "vat_basis": "excludes_vat",
        "vat_basis_unknown": False,
        "vat_basis_note": "trade ex-VAT; buyer not registered → add 20% VAT",
    }
