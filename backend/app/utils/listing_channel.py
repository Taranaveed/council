"""Classify listings as wholesale vs retail for sourcing actions."""
from __future__ import annotations

import re
from typing import Any

_WHOLESALE_HOST_RE = re.compile(
    r"alibaba\.|indiamart\.|made-in-china\.|tradeindia\.|dhgate\.|"
    r"globalsources\.|aliexpress\.|europages\.|thomasnet\.|faire\.|1688\.",
    re.I,
)

_RETAIL_HOST_RE = re.compile(
    r"daraz\.|amazon\.|flipkart\.|ebay\.|walmart\.|noon\.|bestbuy\.|"
    r"priceoye\.|homeshopping\.|telemart\.|shophive\.|olx\.|"
    r"shopify\.|myshopify\.|"
    r"ronin\.pk|audionic\.|interlinkcap\.|saamaan\.|markaz\.app",
    re.I,
)


def classify_listing_channel(listing: dict[str, Any] | None) -> str:
    """Return 'wholesale' | 'retail' | 'unknown'."""
    if not listing or not isinstance(listing, dict):
        return "unknown"
    if listing.get("wholesale") is True:
        return "wholesale"
    link = str(listing.get("link") or "")
    vendor = str(listing.get("vendor") or listing.get("source") or "")
    blob = f"{link} {vendor}"
    if _WHOLESALE_HOST_RE.search(blob):
        return "wholesale"
    if _RETAIL_HOST_RE.search(blob):
        return "retail"
    # Local .pk / .in boutique shops without B2B path → retail for bulk buyers
    if re.search(r"\.(pk|in)(/|$)", link, re.I) and not re.search(
        r"/product-detail/|/proddetail", link, re.I
    ):
        if re.search(r"/products?/", link, re.I):
            return "retail"
    return "unknown"


def annotate_listing_channels(
    listings: list[dict[str, Any]],
    *,
    is_bulk: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in listings or []:
        item = dict(row)
        channel = classify_listing_channel(item)
        item["channel"] = channel
        if is_bulk and channel == "retail":
            item["sourcing_action"] = "ask_bulk_quote"
            item["sourcing_note"] = (
                "Retail listing — ask the seller for a bulk/case quote (MOQ, unit price, lead time)."
            )
        elif channel == "wholesale":
            item["sourcing_action"] = "contact_supplier"
            item["sourcing_note"] = "Wholesale / factory listing — confirm MOQ and tier price on the page."
        else:
            item["sourcing_action"] = "verify_channel" if is_bulk else "retail_ok"
            item["sourcing_note"] = (
                "Channel unclear — confirm whether this is retail or wholesale pricing."
                if is_bulk
                else "Retail browsing — confirm stock and shipping on the seller page."
            )
        out.append(item)
    return out


def bulk_quote_guidance(listings: list[dict[str, Any]], *, is_bulk: bool) -> dict[str, Any] | None:
    if not is_bulk:
        return None
    retail = [r for r in listings or [] if r.get("channel") == "retail" or r.get("sourcing_action") == "ask_bulk_quote"]
    wholesale = [r for r in listings or [] if r.get("channel") == "wholesale"]
    if not retail:
        return None
    return {
        "action": "ask_bulk_quote",
        "message": (
            f"{len(retail)} retail listing(s) in this bulk run — do not treat shelf prices as wholesale. "
            "Ask each retail seller for a bulk quote (quantity, MOQ, unit price, shipping)."
        ),
        "retail_count": len(retail),
        "wholesale_count": len(wholesale),
        "sample_questions": [
            f"Can you quote a bulk/case price for { '{qty}' } units?",
            "What is your MOQ and lead time for a wholesale order?",
            "Does the listed price include shipping, or is it per-piece retail only?",
        ],
    }
