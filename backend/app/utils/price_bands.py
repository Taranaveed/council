"""Load per-category unit-price floor/ceiling bands (GBP).



Wholesale / moq_tier / trade / unknown → shared/price_bands/uk_categories.json

Retail → shared/price_bands/uk_retail_categories.json (higher ceilings)



Soft vs hard: within 3× of a bound → borderline (show with flag);

beyond 3× → hard (hide landed).

"""

from __future__ import annotations



import json

import re

from functools import lru_cache

from pathlib import Path

from typing import Any



_ROOT = Path(__file__).resolve().parents[3]

_WHOLESALE_PATH = _ROOT / "shared" / "price_bands" / "uk_categories.json"

_RETAIL_PATH = _ROOT / "shared" / "price_bands" / "uk_retail_categories.json"



_SOFT_MULTIPLE = 3.0





@lru_cache(maxsize=1)

def load_uk_price_bands() -> dict[str, Any]:

    if not _WHOLESALE_PATH.is_file():

        return {

            "currency": "GBP",

            "default": {"floor_gbp": 0.05, "ceiling_gbp": 80.0},

            "categories": [],

        }

    return json.loads(_WHOLESALE_PATH.read_text(encoding="utf-8"))





@lru_cache(maxsize=1)

def load_uk_retail_price_bands() -> dict[str, Any]:

    if not _RETAIL_PATH.is_file():

        return load_uk_price_bands()

    return json.loads(_RETAIL_PATH.read_text(encoding="utf-8"))





def _is_retail_price_type(price_type: str | None) -> bool:

    return str(price_type or "").strip().lower() == "retail"





def band_for_query(

    query: str | None,

    *,

    price_type: str | None = None,

) -> dict[str, Any]:

    data = (

        load_uk_retail_price_bands()

        if _is_retail_price_type(price_type)

        else load_uk_price_bands()

    )

    q = str(query or "").lower()

    table = "retail" if _is_retail_price_type(price_type) else "wholesale"

    for cat in data.get("categories") or []:

        pat = str(cat.get("match") or "")

        if pat and re.search(pat, q, re.I):

            return {

                "id": cat.get("id"),

                "floor_gbp": float(cat.get("floor_gbp") or 0.05),

                "ceiling_gbp": float(cat.get("ceiling_gbp") or 80.0),

                "source_note": cat.get("source_note"),

                "table": table,

                "price_type": "retail" if table == "retail" else (price_type or "wholesale"),

            }

    default = data.get("default") or {}

    return {

        "id": "default",

        "floor_gbp": float(default.get("floor_gbp") or 0.05),

        "ceiling_gbp": float(default.get("ceiling_gbp") or 80.0),

        "source_note": default.get("source_note"),

        "table": table,

        "price_type": "retail" if table == "retail" else (price_type or "wholesale"),

    }





def within_nx_of_bound(

    value: float | None,

    bound: float | None,

    *,

    n: float = _SOFT_MULTIPLE,

) -> bool:

    """True when value and bound differ by at most n× (soft / borderline)."""

    if value is None or bound is None:

        return False

    try:

        v = float(value)

        b = float(bound)

    except (TypeError, ValueError):

        return False

    if v <= 0 or b <= 0:

        return False

    return max(v, b) / min(v, b) <= float(n) + 1e-9





def within_2x_of_bound(value: float | None, bound: float | None) -> bool:

    """Back-compat alias — soft band is now 3×."""

    return within_nx_of_bound(value, bound, n=_SOFT_MULTIPLE)





def within_3x_of_bound(value: float | None, bound: float | None) -> bool:

    return within_nx_of_bound(value, bound, n=_SOFT_MULTIPLE)





def assess_category_band(

    unit_gbp: float | None,

    query: str | None,

    *,

    price_type: str | None = None,

) -> dict[str, Any]:

    band = band_for_query(query, price_type=price_type)

    if unit_gbp is None or unit_gbp <= 0:

        return {

            "in_band": False,

            "reasons": ["missing_unit"],

            "band": band,

            "guards": [],

            "hard_guards": [],

            "soft_guards": [],

        }

    reasons: list[str] = []

    guards: list[dict[str, Any]] = []

    floor = float(band["floor_gbp"])

    ceiling = float(band["ceiling_gbp"])

    if unit_gbp < floor:

        reasons.append(f"below_floor<{floor}")

        guards.append(

            {

                "rule": "below_floor",

                "bound": floor,

                "bound_kind": "floor_gbp",

                "source_note": band.get("source_note"),

                "category_id": band.get("id"),

                "band_table": band.get("table"),

                "trigger_price_gbp": round(unit_gbp, 4),

                "trigger_kind": "unit",

                "borderline": within_3x_of_bound(unit_gbp, floor),

                "soft_multiple": _SOFT_MULTIPLE,

            }

        )

    if unit_gbp > ceiling:

        reasons.append(f"above_ceiling>{ceiling}")

        guards.append(

            {

                "rule": "above_ceiling",

                "bound": ceiling,

                "bound_kind": "ceiling_gbp",

                "source_note": band.get("source_note"),

                "category_id": band.get("id"),

                "band_table": band.get("table"),

                "trigger_price_gbp": round(unit_gbp, 4),

                "trigger_kind": "unit",

                "borderline": within_3x_of_bound(unit_gbp, ceiling),

                "soft_multiple": _SOFT_MULTIPLE,

            }

        )

    soft = [g for g in guards if g.get("borderline")]

    hard = [g for g in guards if not g.get("borderline")]

    return {

        "in_band": not reasons,

        "reasons": reasons,

        "band": band,

        "unit_gbp": unit_gbp,

        "guards": guards,

        "soft_guards": soft,

        "hard_guards": hard,

        "hide": bool(hard),

        "soft_flag": bool(soft) and not hard,

    }


