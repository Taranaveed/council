"""Order-total sanity: goods vs budget / qty×ceiling → needs_quote / soft flag."""
from __future__ import annotations

from typing import Any

from app.utils.price_bands import band_for_query, within_3x_of_bound


def order_goods_cap_gbp(
    query: str | None,
    quantity: int,
    *,
    price_type: str | None = None,
) -> float:
    """
    Cap = category_ceiling × qty (per price_type retail vs wholesale table).
    No flat ORDER_GOODS_CAP_GBP floor — retail rows use the same formula.
    """
    band = band_for_query(query, price_type=price_type)
    return float(band["ceiling_gbp"]) * max(int(quantity), 1)


def assess_order_total(
    goods_gbp: float | None,
    *,
    query: str | None,
    quantity: int,
    budget_gbp: float | None = None,
    price_type: str | None = None,
) -> dict[str, Any]:
    if goods_gbp is None or goods_gbp <= 0:
        return {
            "needs_quote": False,
            "reasons": [],
            "cap_gbp": None,
            "guards": [],
            "hard_guards": [],
            "soft_guards": [],
            "hide": False,
            "soft_flag": False,
        }

    cap = order_goods_cap_gbp(query, quantity, price_type=price_type)
    band = band_for_query(query, price_type=price_type)
    reasons: list[str] = []
    guards: list[dict] = []
    if budget_gbp is not None and goods_gbp > float(budget_gbp):
        reasons.append(f"goods_over_budget>{budget_gbp}")
        guards.append(
            {
                "rule": "goods_over_budget",
                "bound": float(budget_gbp),
                "bound_kind": "budget_gbp",
                "source_note": "Buyer budget from request",
                "category_id": band.get("id"),
                "band_table": band.get("table"),
                "trigger_price_gbp": round(float(goods_gbp), 2),
                "trigger_kind": "goods_total",
                # Budget overage stays soft only when within 3×
                "borderline": within_3x_of_bound(goods_gbp, float(budget_gbp)),
                "soft_multiple": 3.0,
            }
        )

    if goods_gbp > cap:
        reasons.append(f"goods_over_cap>{cap:.0f}")
        guards.append(
            {
                "rule": "goods_over_cap",
                "bound": round(cap, 2),
                "bound_kind": "order_goods_cap_gbp",
                "source_note": (
                    f"ceiling£{band.get('ceiling_gbp')}×qty={quantity} "
                    f"({band.get('table')}); {band.get('source_note') or ''}"
                ).strip(),
                "category_id": band.get("id"),
                "band_table": band.get("table"),
                "trigger_price_gbp": round(float(goods_gbp), 2),
                "trigger_kind": "goods_total",
                # Order cap is always hard → needs_quote (no 3× soft escape)
                "borderline": False,
                "soft_multiple": 3.0,
            }
        )

    soft = [g for g in guards if g.get("borderline")]
    hard = [g for g in guards if not g.get("borderline")]
    return {
        "needs_quote": bool(hard),
        "reasons": reasons,
        "cap_gbp": cap,
        "goods_gbp": goods_gbp,
        "budget_gbp": budget_gbp,
        "guards": guards,
        "soft_guards": soft,
        "hard_guards": hard,
        "hide": bool(hard),
        "soft_flag": bool(soft) and not hard,
    }
