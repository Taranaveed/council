"""Detect gated UK cash-and-carry / trade portals that rarely expose public prices."""
from __future__ import annotations

import re
from typing import Any

# Brands / hosts known to require trade login — not an endorsement list.
_GATED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bbooker\b", re.I),
    re.compile(r"\bmakro\b", re.I),
    re.compile(r"\bbestway\s*wholesale\b", re.I),
    re.compile(r"\bdhamecha\b", re.I),
    re.compile(r"\bparfetts\b", re.I),
    re.compile(r"\bbidfood\b", re.I),
]


def gated_retail_query_hit(query: str | None) -> str | None:
    q = str(query or "")
    for cre in _GATED_PATTERNS:
        m = cre.search(q)
        if m:
            return m.group(0)
    return None


def gated_retail_warning(query: str | None, *, listing_count: int = 0) -> str | None:
    hit = gated_retail_query_hit(query)
    if not hit:
        return None
    if listing_count > 0:
        return (
            f"Query names gated trade retailer '{hit}'. Prices on member-only "
            "cash-and-carry portals are often hidden without a trade login — "
            "treat any public snippet as incomplete."
        )
    return (
        f"No usable public prices for '{hit}' (gated UK cash-and-carry / trade portal). "
        "Member login is typically required; this is not a silent empty market — "
        "try a brand-neutral product query or a wholesaler that publishes trade list prices."
    )


def merge_gated_warning(warning: str | None, query: str | None, listing_count: int) -> str | None:
    extra = gated_retail_warning(query, listing_count=listing_count)
    if not extra:
        return warning
    if warning and extra in warning:
        return warning
    return f"{warning} {extra}".strip() if warning else extra
