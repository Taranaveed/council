"""Tier selection + reliability (Python mirror of market-service/listingTiers.js)."""
from __future__ import annotations

from typing import Any

from app.utils.money import parse_money


def assess_tiers_reliability(tiers: list[dict[str, Any]] | None) -> dict[str, Any]:
    reasons: list[str] = []
    list_ = [t for t in (tiers or []) if isinstance(t, dict) and int(t.get("min_qty") or 0) > 0]
    if len(list_) <= 1:
        return {"reliable": True, "reasons": []}

    mins = [int(t["min_qty"]) for t in list_]
    if len(set(mins)) != len(mins):
        reasons.append("duplicate_min_qty")

    sorted_t = sorted(list_, key=lambda t: int(t["min_qty"]))
    prev_amt: float | None = None
    prev_min: int | None = None
    for t in sorted_t:
        amt = parse_money(t.get("unit_price"))
        min_q = int(t["min_qty"])
        if amt is None:
            reasons.append("unparseable_tier_price")
            break
        if prev_amt is not None and prev_min is not None and min_q > prev_min and amt > prev_amt * 1.05:
            reasons.append("non_monotonic_rising")
            break
        prev_amt = amt
        prev_min = min_q

    amounts = [parse_money(t.get("unit_price")) for t in sorted_t]
    amounts_f = [a for a in amounts if a is not None]
    if len(amounts_f) >= 2:
        hi, lo = max(amounts_f), min(amounts_f)
        if lo > 0 and hi / lo > 50:
            reasons.append("wild_price_spread")

    return {"reliable": len(reasons) == 0, "reasons": reasons}


def select_tier_for_quantity(
    tiers: list[dict[str, Any]] | None,
    quantity: int | None,
) -> dict[str, Any]:
    """
    Select tier where min_qty <= quantity. If qty < lowest min_qty → moq_not_met.
    Unreliable tiers → no single pick; return unit_price_range instead.
    """
    assessment = assess_tiers_reliability(tiers)
    usable: list[tuple[int, float, dict[str, Any]]] = []
    for t in tiers or []:
        if not isinstance(t, dict):
            continue
        min_q = int(t.get("min_qty") or 0)
        amt = parse_money(t.get("unit_price"))
        if min_q <= 0 or amt is None:
            continue
        usable.append((min_q, amt, t))
    usable.sort(key=lambda x: x[0])

    if not usable or not isinstance(quantity, int) or quantity <= 0:
        return {
            "tier": None,
            "moq_not_met": False,
            "lowest_min_qty": None,
            "tiers_reliable": assessment["reliable"],
            "reliability_reasons": assessment["reasons"],
            "unit_price_range": None,
        }

    amounts = [a for _, a, _ in usable]
    price_range = {"low": min(amounts), "high": max(amounts)}
    lowest = usable[0][0]

    if quantity < lowest:
        return {
            "tier": None,
            "moq_not_met": True,
            "lowest_min_qty": lowest,
            "tiers_reliable": assessment["reliable"],
            "reliability_reasons": assessment["reasons"],
            "unit_price_range": price_range,
        }

    if not assessment["reliable"]:
        return {
            "tier": None,
            "moq_not_met": False,
            "lowest_min_qty": lowest,
            "tiers_reliable": False,
            "reliability_reasons": assessment["reasons"],
            "unit_price_range": price_range,
        }

    chosen = usable[0][2]
    for min_q, _amt, t in usable:
        if quantity >= min_q:
            chosen = t
    return {
        "tier": chosen,
        "moq_not_met": False,
        "lowest_min_qty": lowest,
        "tiers_reliable": True,
        "reliability_reasons": [],
        "unit_price_range": price_range,
    }
