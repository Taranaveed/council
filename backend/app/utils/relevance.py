"""Relevance gate: drop off-category listings; detect ambiguous queries."""
from __future__ import annotations

import re
from typing import Any

from app.utils.conflict_terms import detect_attribute_conflicts
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


_WEAK_QUERY_TOKENS = frozenset(
    {
        "bulk",
        "pack",
        "unit",
        "units",
        "wholesale",
        "supplier",
        "suppliers",
        "blank",
        "set",
        "sets",
        "box",
        "case",
        "cases",
        "with",
        "from",
        "for",
        "the",
        "and",
        "non",
        "slip",
        "cash",
        "carry",
        "known",
        "product",
        "item",
        "items",
        "order",
        "buy",
        "uk",
        # Qualifiers that are not product form — avoid requiring "mobile" on a charger title
        "mobile",
        "phone",
    }
)

# Product-form synonyms: any member satisfies THAT required noun (not other nouns).
# Do not put co-required pairs (foil+rolls) in the same group.
_NOUN_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"earphone", "earphones", "earbud", "earbuds", "handsfree", "handfrees", "headset", "headsets", "headphone", "headphones"}),
    frozenset({"cover", "covers", "case", "cases", "phonecase"}),
    frozenset({"adapter", "adapters", "adaptor", "adaptors", "charger", "chargers"}),
    frozenset({"mug", "mugs", "cup", "cups"}),
    frozenset({"ring", "rings"}),
    frozenset({"notebook", "notebooks", "notepad", "notepads"}),
    frozenset({"towel", "towels"}),
    frozenset({"foil", "foils"}),
    frozenset({"roll", "rolls"}),
)


def _noun_match_forms(noun: str) -> set[str]:
    """Singular/plural stems + synonym group members for one required noun."""
    n = str(noun or "").lower().strip()
    if not n:
        return set()
    forms = {n}
    if n.endswith("ies") and len(n) > 4:
        forms.add(n[:-3] + "y")
    elif n.endswith("ses") and len(n) > 4:
        forms.add(n[:-2])
    elif n.endswith("s") and len(n) > 3 and not n.endswith("ss"):
        forms.add(n[:-1])
    else:
        forms.add(n + "s")
        if n.endswith("y") and len(n) > 2:
            forms.add(n[:-1] + "ies")
    for group in _NOUN_SYNONYM_GROUPS:
        if forms & group or n in group:
            forms |= set(group)
            break
    return forms


def key_product_nouns(query: str) -> list[str]:
    """
    Significant product nouns from the query that must appear in the listing TITLE.
    Drops weak fillers; keeps the last 1–2 content tokens (product head + qualifier).
    Brand-like leading tokens (e.g. nisbets) are optional and omitted from the require set
    when ≥2 content tokens remain after the first.
    """
    q = str(query or "").lower()
    toks = [
        t
        for t in re.split(r"\W+", q)
        if len(t) >= 4 and t not in _WEAK_QUERY_TOKENS
    ]
    if not toks:
        return []
    if len(toks) == 1:
        return toks
    # Drop leading brand/site token when we still have ≥2 product nouns
    # e.g. "nisbets catering foil rolls" → foil, rolls (catering kept if only 3)
    content = toks[1:] if len(toks) >= 3 else toks
    # Prefer the last two content nouns (product + form)
    selected = content[-2:] if len(content) >= 2 else content
    # Brand/model tokens (iphone, …) are optional when a known product-form noun remains
    form_nouns = [
        n
        for n in selected
        if any(_noun_match_forms(n) & g for g in _NOUN_SYNONYM_GROUPS)
    ]
    if form_nouns and len(form_nouns) < len(selected):
        return form_nouns
    return selected


def title_has_key_product_nouns(listing: dict[str, Any], query: str) -> bool:
    """ALL rows (retail + UK + wholesale) must carry key product nouns in the title."""
    nouns = key_product_nouns(query)
    if not nouns:
        return True
    title = str(listing.get("title") or "").lower()
    if not title.strip():
        return False
    for noun in nouns:
        forms = _noun_match_forms(noun)
        if not any(re.search(rf"\b{re.escape(f)}\b", title) for f in forms):
            # Fallback: substring for short compound titles without clear word bounds
            if not any(f in title for f in forms):
                return False
    return True


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
    if listing.get("attribute_conflicts"):
        return False
    if listing.get("price_outlier") or listing.get("unit_price_unreliable"):
        return False

    # Key product nouns must appear in the TITLE for every row (retail + UK + wholesale)
    if not title_has_key_product_nouns(listing, query):
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
    # UK Shopping retail comps with a usable SERP price enter the comparison
    # pool (never Best) even though they are not product-detail pages.
    if listing.get("uk_retail_priced") and listing.get("counts_as_priced_comparison"):
        price = str(listing.get("price") or listing.get("extracted_price") or "")
        if re.match(r"^(see listing|n/?a)$", price, re.I):
            return False
        if listing.get("unit_price_rejected"):
            return False
        return parse_money(price) is not None
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
    found_n = 0
    relevant_n = 0
    for row in listings or []:
        item = dict(row)
        conflicts = detect_attribute_conflicts(item, query)
        if conflicts:
            item["attribute_conflicts"] = conflicts
            item["spec_ok"] = False
        # found = product-detail / reviewable URLs entering the gate
        if is_reviewable_product_listing(item) or is_priced_product_listing(item):
            found_n += 1
        if not is_priced_product_listing(item):
            item["drop_reason"] = "not_priced_product_page"
            dropped.append(item)
            continue
        if item.get("wired_conflict") or item.get("spec_ok") is False or item.get("spec_misses") or item.get("attribute_conflicts"):
            item["drop_reason"] = "must_have_miss"
            item["counts_as_live_listing"] = False
            dropped.append(item)
            continue
        # Bulk: retail shelf prices must not enter the wholesale pool —
        # except UK Shopping comps that carry a usable extracted_price
        # (counted as priced retail/unit; never Best).
        if is_bulk and not item.get("uk_retail_priced") and (
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
        relevant_n += 1
        if item.get("uk_retail_priced") or item.get("price_type") == "retail":
            item["counts_as_live_listing"] = False
            item["counts_as_priced_comparison"] = True
            item["best_pick_eligible"] = False
            item["price_type"] = item.get("price_type") or "retail"
            item["sourcing_note"] = item.get("sourcing_note") or (
                "single-unit retail price; confirm quantity limits and bulk discount"
            )
        else:
            item["counts_as_live_listing"] = True
        kept.append(item)

    # Outlier + implausible metal check only among category-relevant peers
    kept = annotate_price_outliers(kept, query=query)
    still_kept: list[dict[str, Any]] = []
    for item in kept:
        # Unpriced UK Shopping review-only rows stay out of comps
        if item.get("price_review_only") and not item.get("uk_retail_priced"):
            item["drop_reason"] = "uk_seller_review_only"
            item["counts_as_live_listing"] = False
            item["best_pick_eligible"] = False
            dropped.append(item)
            continue
        if item.get("is_uk_shopping_seller") and not item.get("uk_retail_priced"):
            item["drop_reason"] = "uk_seller_review_only"
            item["counts_as_live_listing"] = False
            item["best_pick_eligible"] = False
            dropped.append(item)
            continue
        if item.get("uk_retail_priced"):
            item["best_pick_eligible"] = False
            # Keep retail comps in the pool; category/order guards hide absurd
            # landeds later. Only drop hard needs_quote / metal nonsense.
            if item.get("implausible_metal") or (
                item.get("needs_quote") and not item.get("uk_has_usable_price")
            ):
                item["drop_reason"] = "needs_quote" if item.get("needs_quote") else "price_outlier"
                item["counts_as_live_listing"] = False
                dropped.append(item)
                continue
            # Category-band flags still flow into landed via price_flagged
            still_kept.append(item)
            continue
        if (
            item.get("price_outlier")
            or item.get("price_flagged")
            or item.get("unit_price_unreliable")
            or item.get("implausible_metal")
            or item.get("needs_quote")
        ):
            item["drop_reason"] = "price_outlier" if not item.get("needs_quote") else "needs_quote"
            item["counts_as_live_listing"] = False
            if item.get("price_outlier_reason") and not item.get("rank_reason"):
                item["rank_reason"] = item["price_outlier_reason"]
            dropped.append(item)
            continue
        still_kept.append(item)
    kept = still_kept

    # Single definition used by UI receipts:
    #   found    = product-detail / reviewable pages entering the gate
    #   relevant = passed category / key-noun / conflict checks (pre-outlier)
    #   priced   = final kept pool with parseable plausible unit price
    listing_counts = {
        "found": found_n,
        "relevant": relevant_n,
        "priced": len(kept),
    }
    meta = {
        "relevant_priced_count": len(kept),
        "dropped_count": len(dropped),
        "no_good_matches": len(kept) < 2,
        "outlier_dropped": sum(
            1 for d in dropped if d.get("drop_reason") in ("price_outlier", "needs_quote")
        ),
        "spec_dropped": sum(1 for d in dropped if d.get("drop_reason") == "must_have_miss"),
        "retail_dropped": sum(1 for d in dropped if d.get("drop_reason") == "retail_in_bulk"),
        "uk_seller_review_only": sum(
            1 for d in dropped if d.get("drop_reason") == "uk_seller_review_only"
        ),
        "uk_retail_priced_count": sum(
            1 for k in kept if k.get("uk_retail_priced")
        ),
        "listing_counts": listing_counts,
    }
    return kept, dropped, meta


def no_good_matches_verdict(query: str, *, dropped: int = 0) -> dict[str, Any]:
    reason = (
        f"No good matches for “{query}”. "
        f"Fewer than 2 relevant product-detail listings with a parseable unit price"
        + (f" ({dropped} off-category or storefront rows dropped)" if dropped else "")
        + ". Refine your query (e.g. “USB wall charger adapter wholesale”)."
    )
    return {
        "verdict": "NO_MATCH",
        # NO_MATCH must not surface a supplier as winner
        "winner": None,
        "summary": (
            f"No good matches for “{query}”. Refine your query — we will not invent a Best pick."
        ),
        "no_match_reason": reason,
        "alternatives": [],
        "agent_breakdown": {
            "thrift_advocate": "Insufficient relevant product pages to recommend a buy.",
            "risk_analyst": "Off-category or storefront-only results are not usable evidence.",
            "contextual_persona": "Ask the buyer to clarify the exact product before searching again.",
        },
    }
