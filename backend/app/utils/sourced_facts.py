"""Strip unsourced marketplace coverage brand names from agent prose."""
from __future__ import annotations

import re
from typing import Any

# Brand-named buyer protections that models invent from training data.
# Allowed only when the exact phrase appears in live listing / marketplace
# profile text for THIS run. (eBay "Money Back Guarantee" is injected via
# marketplace system prompt when that marketplace is selected — pass it in
# extra_sourced so it is not stripped.)
_COVERAGE_BRANDS = (
    "Trade Assurance",
    "A-to-z Guarantee",
    "A-to-Z Guarantee",
)

_GENERIC = "on-platform payment with chargeback protection"


def listing_facts_blob(listings: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for row in listings or []:
        if not isinstance(row, dict):
            continue
        for key in (
            "title",
            "snippet",
            "description",
            "extensions",
            "page_facts",
            "badges",
            "guarantees",
            "services",
            "highlights",
            "vendor",
            "raw",
        ):
            val = row.get(key)
            if val is None:
                continue
            if isinstance(val, str):
                parts.append(val)
            else:
                parts.append(str(val))
    return "\n".join(parts)


def scrub_unsourced_coverage_brands(
    text: str,
    *,
    sourced_blob: str,
) -> str:
    """
    Replace coverage brand names that do not appear in sourced_blob
    with generic harm-reduction wording.
    """
    if not text:
        return text
    out = text
    for brand in _COVERAGE_BRANDS:
        if brand in sourced_blob:
            continue
        if brand not in out:
            continue
        # Prefer dropping "Alibaba's Trade Assurance" / "via Trade Assurance" cleanly
        out = re.sub(
            rf"(?i)\b(?:alibaba(?:'s)?\s+)?{re.escape(brand)}\b",
            _GENERIC,
            out,
        )
    return out


def scrub_agent_texts(
    texts: dict[str, str] | list[str] | None,
    *,
    listings: list[dict[str, Any]] | None,
    extra_sourced: str = "",
) -> dict[str, str] | list[str] | None:
    sourced = listing_facts_blob(listings) + "\n" + (extra_sourced or "")
    if texts is None:
        return None
    if isinstance(texts, dict):
        return {
            k: scrub_unsourced_coverage_brands(str(v or ""), sourced_blob=sourced)
            for k, v in texts.items()
        }
    if isinstance(texts, list):
        return [
            scrub_unsourced_coverage_brands(str(v or ""), sourced_blob=sourced)
            for v in texts
        ]
    return texts
