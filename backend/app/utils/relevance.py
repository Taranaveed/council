"""Relevance gate: drop off-category listings; detect ambiguous queries."""
from __future__ import annotations

import re
from typing import Any

from app.utils.money import parse_money
from app.utils.spec_check import listing_satisfies_wired_intent

# Query category → listing must hit at least one positive; hard negatives always drop.
# (positives, negatives, require_positive: if True, soft query-token fallback is disabled)
_CATEGORY_RULES: list[tuple[re.Pattern[str], list[str], list[str], bool]] = [
    (
        re.compile(r"\b(adapter|adapters|otg|charger|usb)\b", re.I),
        [
            "adapter",
            "otg",
            "charger",
            "usb",
            "type-c",
            "type c",
            "lightning",
            "dongle",
            "hub",
            "wall plug",
            "power adapter",
            "plug adapter",
            "pd charger",
            "fast charger",
        ],
        [
            "window",
            "camper",
            "wallpaper",
            "curtain",
            "truck",
            "van loaded",
            "food truck",
            "street truck",
            "bathroom",
            "tile",
            "paint",
            "sofa",
            "mattress",
            "smartphone",
            "mobile phone",
            "cell phone",
            "android phone",
            "global version",
            "16g+",
            "1tb",
            "5g phone",
            "iphone",
            "galaxy s",
        ],
        True,  # must include an adapter/charger positive — "mobile" alone is not enough
    ),
    (
        re.compile(r"\b(cover|covers|case|cases|phonecase)\b", re.I),
        [
            "cover",
            "covers",
            "case",
            "cases",
            "phonecase",
            "folio",
            "flip",
            "protective",
            "silicone",
            "tpu",
            "back cover",
            "mobile cover",
            "phone case",
        ],
        [
            "tooling",
            "crafting",
            "leather sheet",
            "vinyl lp",
            "backgammon",
            "food truck",
            "smartphone",
            "mobile phone",
            "cell phone",
            "android phone",
            "global version",
            "1tb",
            "5g phone",
        ],
        True,
    ),
    (
        re.compile(r"\b(jewel|ring|pendant|earring|necklace|bracelet|silver|gold)\b", re.I),
        ["jewel", "ring", "pendant", "earring", "necklace", "bracelet", "silver", "gold", "925"],
        ["handbag", "tote", "purse", "wallet", "luggage", "backpack"],
        True,
    ),
    (
        re.compile(r"\b(earphone|earphones|handsfree|earbud|headphone|headset)\b", re.I),
        ["earphone", "earbud", "handsfree", "headphone", "headset", "tws", "bluetooth", "wired"],
        ["wallpaper", "curtain", "camper", "window", "truck", "mobile phone"],
        True,
    ),
    (
        re.compile(r"\b(body\s*mist|body\s*spray|perfume)\b", re.I),
        ["mist", "spray", "perfume", "fragrance", "cologne"],
        ["wallpaper", "paint", "cleaner", "detergent"],
        True,
    ),
]

_AMBIGUOUS: dict[str, dict[str, Any]] = {
    "mobile adapters": {
        "reason": "ambiguous adapter type",
        "options": [
            "USB wall charger adapter wholesale",
            "OTG USB-C adapter wholesale",
            "3.5mm headphone jack adapter wholesale",
            "SIM card adapter wholesale",
        ],
        "suggestion": "USB wall charger adapter wholesale",
    },
    "mobile adapter": {
        "reason": "ambiguous adapter type",
        "options": [
            "USB wall charger adapter wholesale",
            "OTG USB-C adapter wholesale",
            "3.5mm headphone jack adapter wholesale",
            "SIM card adapter wholesale",
        ],
        "suggestion": "USB wall charger adapter wholesale",
    },
    "usb wall mobile adapters": {
        "reason": "clarify wall charger vs phone accessory",
        "options": [
            "USB wall charger adapter wholesale",
            "OTG USB-C adapter wholesale",
            "USB-C car charger wholesale",
        ],
        "suggestion": "USB wall charger adapter wholesale",
    },
    "adapters": {
        "reason": "ambiguous adapter type",
        "options": [
            "USB wall charger adapter wholesale",
            "OTG USB-C adapter wholesale",
            "travel plug adapter wholesale",
        ],
        "suggestion": "USB wall charger adapter wholesale",
    },
}

_PHONE_DEVICE_RE = re.compile(
    r"\b("
    r"smartphone|mobile\s+phone|cell\s+phone|android\s+phone|"
    r"iphone\s*\d|galaxy\s*s\d|global\s+version|"
    r"\d+\s*g\s*\+\s*\d+\s*tb|\d+gb\s*\+\s*\d+\s*tb|"
    r"food\s*truck|street\s*truck|drivable\s+mobile|bakery\s+food"
    r")\b",
    re.I,
)
_ACCESSORY_OK_RE = re.compile(
    r"\b(adapter|charger|otg|cable|usb|dongle|hub|plug|wall\s*wart|power\s*bank)\b",
    re.I,
)


def _blob(listing: dict[str, Any]) -> str:
    parts = [
        str(listing.get("title") or ""),
        str(listing.get("snippet") or ""),
        str(listing.get("note") or ""),
    ]
    for v in listing.get("variants") or []:
        if isinstance(v, dict):
            parts.append(str(v.get("label") or ""))
    return " ".join(parts).lower()


def _is_product_url(link: str) -> bool:
    u = (link or "").lower()
    return bool(re.search(r"/product-detail/|/products?/|/proddetail|/item/|/itm/|/dp/", u))


def detect_ambiguous_query(item_name: str) -> dict[str, Any] | None:
    key = re.sub(r"\s+", " ", str(item_name or "").strip().lower())
    if key in _AMBIGUOUS:
        return {"vague": True, **_AMBIGUOUS[key], "original": item_name}
    if re.fullmatch(r"mobile\s+adapters?", key) or re.fullmatch(r"phone\s+adapters?", key):
        return {"vague": True, **_AMBIGUOUS["mobile adapters"], "original": item_name}
    # "usb wall mobile adapters" / "mobile usb adapters" — still ambiguous / phone-heavy
    if re.search(r"\bmobile\b", key) and re.search(r"\badapters?\b", key) and not re.search(
        r"\b(charger|otg|wall\s*charger|type-?c|lightning|sim)\b", key
    ):
        return {"vague": True, **_AMBIGUOUS["usb wall mobile adapters"], "original": item_name}
    return None


def listing_relevant_to_query(listing: dict[str, Any], query: str) -> bool:
    q = str(query or "").lower()
    blob = _blob(listing)
    if not q or not blob:
        return True

    # Hard must-have / contradiction — never count toward relevant pool
    if listing.get("wired_conflict") or listing.get("spec_ok") is False:
        return False
    if listing.get("spec_misses"):
        return False
    if listing.get("price_outlier") or listing.get("unit_price_unreliable"):
        return False

    # Wired audio query → drop Bluetooth / TWS / wireless-only titles
    if not listing_satisfies_wired_intent(listing, query):
        return False

    # Hard reject phone handsets / food trucks when the query is an accessory
    if re.search(r"\b(adapter|adapters|otg|charger|usb|cable)\b", q):
        if _PHONE_DEVICE_RE.search(blob) and not _ACCESSORY_OK_RE.search(blob):
            return False
        # "Wholesale Mobile Phone" with no accessory word
        if re.search(r"\bmobile\s+phone\b|\bsmartphone\b", blob) and not _ACCESSORY_OK_RE.search(
            blob
        ):
            return False

    for q_re, positives, negatives, require_positive in _CATEGORY_RULES:
        if not q_re.search(q):
            continue
        # Hard negatives always drop unless listing also has a category positive
        if any(n in blob for n in negatives):
            if not any(p in blob for p in positives):
                return False

        has_positive = any(p in blob for p in positives)
        if require_positive and positives and not has_positive:
            return False
        if positives and not has_positive:
            q_tokens = [t for t in re.split(r"\W+", q) if len(t) >= 4]
            # Ignore weak tokens that match wrong categories (mobile, phone, wall alone)
            weak = {"mobile", "phone", "wall", "bulk", "pack", "unit", "wholesale", "supplier"}
            q_tokens = [t for t in q_tokens if t not in weak]
            if q_tokens and not any(t in blob for t in q_tokens):
                return False
    return True


def is_priced_product_listing(listing: dict[str, Any]) -> bool:
    if listing.get("counts_as_live_listing") is False:
        return False
    if listing.get("is_product_page") is False:
        return False
    link = str(listing.get("link") or "")
    if not _is_product_url(link) and not listing.get("is_product_page"):
        return False
    price = str(listing.get("price") or "")
    if re.match(r"^(see listing|n/?a)$", price, re.I):
        # Wholesale product URL with unit_usd from ranker still counts
        unit = listing.get("unit_usd")
        if unit is not None:
            try:
                return float(unit) > 0
            except (TypeError, ValueError):
                return False
        return False
    if listing.get("unit_price_rejected") or str(listing.get("price_source") or "") == "rejected_storefront":
        return False
    return parse_money(price) is not None


def is_reviewable_product_listing(listing: dict[str, Any]) -> bool:
    """Product-detail URL worth showing even without a parseable unit price."""
    if listing.get("is_product_page") is False:
        return False
    link = str(listing.get("link") or "")
    if not _is_product_url(link) and not listing.get("is_product_page"):
        return False
    if listing.get("unit_price_rejected") or str(listing.get("price_source") or "") == "rejected_storefront":
        return False
    if listing.get("wired_conflict") or listing.get("spec_ok") is False:
        return False
    return True


def filter_relevant_priced_listings(
    listings: list[dict[str, Any]],
    query: str,
    *,
    is_bulk: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """
    Returns (kept, dropped, meta).
    kept = relevant product-detail listings with a parseable, plausible unit price
    that satisfy stated must-have attributes.
    In bulk mode, retail shelf listings are hard-excluded (not comparable to wholesale).
    """
    from app.utils.price_plausibility import annotate_price_outliers

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in listings or []:
        item = dict(row)
        if not is_priced_product_listing(item):
            item["drop_reason"] = "not_priced_product_page"
            dropped.append(item)
            continue
        if item.get("wired_conflict") or item.get("spec_ok") is False or item.get("spec_misses"):
            item["drop_reason"] = "must_have_miss"
            item["counts_as_live_listing"] = False
            dropped.append(item)
            continue
        # Bulk: retail shelf prices must not enter the relevant/wholesale pool
        if is_bulk and (
            item.get("sourcing_action") == "ask_bulk_quote"
            or item.get("channel") == "retail"
        ):
            item["drop_reason"] = "retail_in_bulk"
            item["counts_as_live_listing"] = False
            item["rank_reason"] = (
                "Retail listing — shelf price is not a wholesale unit cost "
                "(excluded from ranking; ask seller for MOQ/case quote)."
            )
            dropped.append(item)
            continue
        if not listing_relevant_to_query(item, query):
            item["drop_reason"] = "off_category"
            dropped.append(item)
            continue
        item["counts_as_live_listing"] = True
        kept.append(item)

    # Outlier + implausible metal check only among category-relevant peers
    kept = annotate_price_outliers(kept, query=query)
    still_kept: list[dict[str, Any]] = []
    for item in kept:
        if item.get("price_outlier") or item.get("unit_price_unreliable") or item.get("implausible_metal"):
            item["drop_reason"] = "price_outlier"
            item["counts_as_live_listing"] = False
            if item.get("price_outlier_reason") and not item.get("rank_reason"):
                item["rank_reason"] = item["price_outlier_reason"]
            dropped.append(item)
            continue
        still_kept.append(item)
    kept = still_kept

    meta = {
        "relevant_priced_count": len(kept),
        "dropped_count": len(dropped),
        "no_good_matches": len(kept) < 2,
        "outlier_dropped": sum(1 for d in dropped if d.get("drop_reason") == "price_outlier"),
        "spec_dropped": sum(1 for d in dropped if d.get("drop_reason") == "must_have_miss"),
        "retail_dropped": sum(1 for d in dropped if d.get("drop_reason") == "retail_in_bulk"),
    }
    return kept, dropped, meta


def no_good_matches_verdict(query: str, *, dropped: int = 0) -> dict[str, Any]:
    return {
        "verdict": "NO_MATCH",
        "winner": {
            "title": "",
            "vendor": "",
            "price": "",
            "link": "",
            "reason": (
                f"No good matches for “{query}”. "
                f"Fewer than 2 relevant product-detail listings with a parseable unit price"
                + (f" ({dropped} off-category or storefront rows dropped)" if dropped else "")
                + ". Refine your query (e.g. “USB wall charger adapter wholesale”)."
            ),
        },
        "summary": (
            f"No good matches for “{query}”. Refine your query — we will not invent a Best pick."
        ),
        "alternatives": [],
        "agent_breakdown": {
            "thrift_advocate": "Insufficient relevant product pages to recommend a buy.",
            "risk_analyst": "Off-category or storefront-only results are not usable evidence.",
            "contextual_persona": "Ask the buyer to clarify the exact product before searching again.",
        },
    }
