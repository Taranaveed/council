"""Label Google Shopping / UK merchants and classify seller-origin evidence.



confirmed_UK hard evidence:

  - .co.uk host/name

  - UK address / UK shipping origin text

  - known_uk_company match (Argos, Currys, …) with per-entry source note



likely_UK: other known_retailers without hard evidence (legacy override list)

unknown: no evidence; marketplace sellers (eBay, Amazon marketplace) always unknown



Only confirmed_UK uses domestic duty 0 / import VAT 0.

"""

from __future__ import annotations



import json

import re

from functools import lru_cache

from pathlib import Path

from typing import Any

from urllib.parse import urlparse



from app.utils.money import parse_money



_ROOT = Path(__file__).resolve().parents[3]

_SELLERS_PATH = _ROOT / "shared" / "uk_sellers" / "known_retailers.json"

_KNOWN_UK_PATH = _ROOT / "shared" / "uk_sellers" / "known_uk_companies.json"



_LABEL_RETAIL = (

    "single-unit retail price; confirm quantity limits and bulk discount"

)



_MARKETPLACE_MERCHANT_RE = re.compile(

    r"^\s*("

    r"ebay\s*[-–—]"

    r"|ebay\.uk\b"

    r"|ebay\b(?!\.co\.uk)"

    r"|amazon\.co\.uk\s*[-–—]"  # Amazon marketplace seller line

    r"|amazon\s*[-–—]"

    r")",

    re.I,

)



_BRANDED_MERCHANTS = {

    "apple",

    "jbl",

    "jbl official",

    "sony",

    "samsung",

    "beats",

    "bose",

    "nike",

    "adidas",

    "dyson",

    "microsoft",

    "google",

    "logitech",

}



_unrecognized_merchants: list[dict[str, Any]] = []



_ORIGIN_CONFIRMED = "confirmed_UK"

_ORIGIN_LIKELY = "likely_UK"

_ORIGIN_SELLS = "sells_to_UK_only"

_ORIGIN_UNKNOWN = "unknown"





def reset_unrecognized_merchants() -> None:

    _unrecognized_merchants.clear()





def get_unrecognized_merchants() -> list[dict[str, Any]]:

    return list(_unrecognized_merchants)





@lru_cache(maxsize=1)

def _seller_data() -> dict[str, Any]:

    if not _SELLERS_PATH.is_file():

        return {"domains": [], "name_patterns": [], "marketplace_patterns": []}

    return json.loads(_SELLERS_PATH.read_text(encoding="utf-8"))





@lru_cache(maxsize=1)

def _known_uk_companies() -> list[dict[str, Any]]:

    if not _KNOWN_UK_PATH.is_file():

        return []

    data = json.loads(_KNOWN_UK_PATH.read_text(encoding="utf-8"))

    return list(data.get("companies") or [])





def _vendor_blob(listing: dict[str, Any]) -> str:

    parts = [

        listing.get("vendor"),

        listing.get("source"),

        listing.get("merchant"),

        listing.get("merchant_name"),

        listing.get("host"),

        listing.get("link"),

        listing.get("product_link"),

        listing.get("displayed_link"),

    ]

    return " ".join(str(p) for p in parts if p).lower()





def merchant_name(listing: dict[str, Any] | None) -> str:

    if not listing:

        return ""

    return str(

        listing.get("merchant")

        or listing.get("merchant_name")

        or listing.get("source")

        or listing.get("vendor")

        or ""

    ).strip()





def product_link_host(listing: dict[str, Any] | None) -> str:

    if not listing:

        return ""

    for key in ("product_link", "link", "displayed_link"):

        raw = str(listing.get(key) or "")

        try:

            host = (urlparse(raw).hostname or "").lower().removeprefix("www.")

            if host:

                return host

        except Exception:

            continue

    return str(listing.get("host") or "").lower().removeprefix("www.")





def delivery_text(listing: dict[str, Any] | None) -> str:

    if not listing:

        return ""

    parts = [

        listing.get("delivery"),

        listing.get("shipping"),

        listing.get("delivery_info"),

        listing.get("ship_to"),

    ]

    return " ".join(str(p) for p in parts if p).strip()





def is_google_shopping_link(link: str | None) -> bool:

    u = str(link or "").lower()

    return "google.com/search" in u and ("ibp=oshop" in u or "tbm=shop" in u)





def usable_extracted_price(listing: dict[str, Any] | None) -> float | None:

    if not listing:

        return None

    for key in ("extracted_price", "price", "price_text"):

        raw = listing.get(key)

        if raw is None or raw == "":

            continue

        if key == "price" and re.match(r"^(see listing|n/?a)$", str(raw), re.I):

            continue

        amt = parse_money(str(raw))

        if amt is not None and amt > 0:

            return float(amt)

    return None





def is_marketplace_seller(listing: dict[str, Any] | None) -> bool:

    """eBay / Amazon marketplace sellers — never origin evidence."""

    mer = merchant_name(listing)

    if not mer:

        return False

    if _MARKETPLACE_MERCHANT_RE.search(mer):

        return True

    data = _seller_data()

    low = mer.lower()

    for pat in data.get("marketplace_patterns") or ["ebay -", "ebay.uk"]:

        if str(pat).lower() in low and ".co.uk" not in low.replace("amazon.co.uk", ""):

            # "ebay - foo" yes; plain amazon.co.uk (no seller dash) handled below

            if "ebay" in str(pat).lower():

                return True

    if re.fullmatch(r"ebay", mer, re.I):

        return True

    # Amazon.co.uk - SellerName

    if re.search(r"amazon\.co\.uk\s*[-–—]", mer, re.I):

        return True

    return False





def is_branded_goods_merchant(listing: dict[str, Any] | None) -> bool:

    mer = merchant_name(listing).lower()

    if not mer:

        return False

    if mer in _BRANDED_MERCHANTS:

        return True

    for brand in _BRANDED_MERCHANTS:

        if re.search(rf"\b{re.escape(brand)}\b", mer):

            return True

    return False





def match_known_uk_company(listing: dict[str, Any] | None) -> dict[str, str] | None:

    """Return {id, pattern, source_note, evidence} if merchant matches a known UK company."""

    if not listing:

        return None

    mer = merchant_name(listing).lower()

    blob = _vendor_blob(listing)

    for co in _known_uk_companies():

        for pat in co.get("patterns") or []:

            p = str(pat).lower().strip()

            if not p:

                continue

            if re.search(rf"\b{re.escape(p)}\b", mer) or p in mer or p in blob:

                return {

                    "id": str(co.get("id") or p),

                    "pattern": p,

                    "source_note": str(co.get("source_note") or ""),

                    "evidence": f"known_uk_company:{co.get('id') or p}",

                }

    return None





def _co_uk_evidence(listing: dict[str, Any]) -> list[str]:

    evidence: list[str] = []

    mer = merchant_name(listing)

    if re.search(r"\.co\.uk\b", mer, re.I):

        evidence.append(f"co.uk_in_merchant:{mer[:60]}")

    host = product_link_host(listing)

    if host.endswith(".co.uk"):

        evidence.append(f"co.uk_host:{host}")

    return evidence





def _uk_ship_from_evidence(listing: dict[str, Any]) -> list[str]:

    evidence: list[str] = []

    ship = delivery_text(listing)

    if not ship:

        return evidence

    low = ship.lower()

    if re.search(

        r"\b(ships?\s+from\s+(the\s+)?(uk|united kingdom|great britain|england|scotland|wales)"

        r"|from\s+(the\s+)?(uk|united kingdom)"

        r"|dispatched\s+from\s+(the\s+)?(uk|united kingdom)"

        r"|uk\s+warehouse|based\s+in\s+(the\s+)?(uk|united kingdom)"

        r"|united kingdom\b.*\b(address|warehouse|seller))",

        low,

    ):

        evidence.append(f"uk_ship_from:{ship[:80]}")

    if re.search(

        r"\b(united kingdom|england|scotland|wales)\b.*\b(road|street|lane|industrial|estate)\b"

        r"|\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b",

        ship,

        re.I,

    ):

        evidence.append(f"uk_address:{ship[:80]}")

    return evidence





def _uk_deliver_to_evidence(listing: dict[str, Any]) -> list[str]:

    ship = delivery_text(listing)

    if not ship:

        return []

    low = ship.lower()

    if re.search(

        r"\b(deliver(?:y|s)?|ships?)\s+to\s+(the\s+)?(uk|united kingdom|great britain)\b"

        r"|\b(uk|united kingdom)\s+delivery\b"

        r"|\bto\s+(the\s+)?(uk|united kingdom)\s+only\b",

        low,

    ):

        return [f"uk_deliver_to:{ship[:80]}"]

    return []





def _known_retailer_match(blob: str, mer: str) -> str | None:

    data = _seller_data()

    low_mer = (mer or "").lower()

    for pat in data.get("marketplace_patterns") or ["ebay -", "ebay.uk"]:

        if str(pat).lower() in low_mer:

            return None

    for dom in data.get("domains") or []:

        d = str(dom).lower()

        if d in blob and d != "ebay.co.uk":

            return f"known_domain:{dom}"

    for pat in data.get("name_patterns") or []:

        p = str(pat).lower()

        if not p or p.startswith("ebay"):

            continue

        if p in blob:

            return f"known_name:{pat}"

    return None





def classify_uk_seller_origin(listing: dict[str, Any] | None) -> dict[str, Any]:

    if not listing or not isinstance(listing, dict):

        return {

            "origin_class": _ORIGIN_UNKNOWN,

            "evidence": [],

            "hard_evidence": [],

            "known_retailer": None,

            "known_uk_company": None,

            "is_marketplace": False,

            "branded_goods": False,

        }



    marketplace = is_marketplace_seller(listing)

    branded = is_branded_goods_merchant(listing)

    deliver_only = _uk_deliver_to_evidence(listing)



    # Marketplaces never become confirmed/likely via name lists

    if marketplace:

        return {

            "origin_class": _ORIGIN_UNKNOWN,

            "evidence": ["marketplace_seller"] + deliver_only,

            "hard_evidence": [],

            "known_retailer": None,

            "known_uk_company": None,

            "is_marketplace": True,

            "branded_goods": branded,

        }



    hard: list[str] = []

    hard.extend(_co_uk_evidence(listing))

    hard.extend(_uk_ship_from_evidence(listing))

    known_co = match_known_uk_company(listing)

    if known_co:

        hard.append(known_co["evidence"])



    blob = _vendor_blob(listing)

    mer = merchant_name(listing)

    known = _known_retailer_match(blob, mer)



    if hard:

        return {

            "origin_class": _ORIGIN_CONFIRMED,

            "evidence": hard

            + deliver_only

            + ([known] if known else [])

            + (

                [f"source_note:{known_co['source_note']}"]

                if known_co and known_co.get("source_note")

                else []

            ),

            "hard_evidence": hard,

            "known_retailer": known,

            "known_uk_company": known_co,

            "is_marketplace": False,

            "branded_goods": branded,

        }

    if known:

        return {

            "origin_class": _ORIGIN_LIKELY,

            "evidence": [known] + deliver_only,

            "hard_evidence": [],

            "known_retailer": known,

            "known_uk_company": None,

            "is_marketplace": False,

            "branded_goods": branded,

        }

    if deliver_only:

        return {

            "origin_class": _ORIGIN_SELLS,

            "evidence": deliver_only,

            "hard_evidence": [],

            "known_retailer": None,

            "known_uk_company": None,

            "is_marketplace": False,

            "branded_goods": branded,

        }

    return {

        "origin_class": _ORIGIN_UNKNOWN,

        "evidence": [],

        "hard_evidence": [],

        "known_retailer": None,

        "known_uk_company": None,

        "is_marketplace": False,

        "branded_goods": branded,

    }





def infer_price_type(listing: dict[str, Any] | None) -> str:

    if not listing:

        return "unknown"

    if (

        listing.get("uk_retail_priced")

        or listing.get("price_type") == "retail"

        or listing.get("channel") in ("uk_retail_shopping", "retail")

        or listing.get("is_shopping_offer")

        or is_google_shopping_link(str(listing.get("link") or ""))

    ):

        return "retail"

    if listing.get("price_type") in ("trade", "moq_tier", "retail", "unknown"):

        return str(listing["price_type"])

    tiers = listing.get("price_tiers")

    if (

        listing.get("price_source") in ("tier_selected", "tier", "page")

        and isinstance(tiers, list)

        and tiers

    ) or (

        listing.get("moq") is not None

        and listing.get("tiers_reliable")

        and isinstance(tiers, list)

        and len(tiers) > 0

    ):

        return "moq_tier"

    host = product_link_host(listing)

    vendor = str(listing.get("vendor") or listing.get("supplier_id") or "").lower()

    if any(

        x in host or x in vendor

        for x in (

            "alibaba",

            "dhgate",

            "made-in-china",

            "globalsources",

            "indiamart",

            "1688.",

        )

    ) or listing.get("wholesale") or listing.get("supplier_type") in (

        "factory",

        "wholesaler",

        "trading",

    ):

        return "trade"

    return "unknown"





def review_classification_reason(listing: dict[str, Any]) -> str:

    bits: list[str] = []

    link = str(listing.get("link") or "")

    if listing.get("is_shopping_offer") or is_google_shopping_link(link):

        bits.append("google_shopping_offer_not_product_page")

    if str(listing.get("price_source") or "") == "rejected_storefront":

        bits.append("rejected_storefront")

    if usable_extracted_price(listing) is None:

        bits.append("no_usable_extracted_price")

    else:

        bits.append("has_extracted_price_retail_comp")

    host = product_link_host(listing)

    if host in ("google.com", "www.google.com"):

        bits.append("product_link_host=google.com")

    return "; ".join(bits) if bits else "uk_shopping_review"





def infer_uk_shopping_seller(listing: dict[str, Any] | None) -> dict[str, Any] | None:

    if not listing or not isinstance(listing, dict):

        return None

    shopping = is_google_shopping_link(str(listing.get("link") or "")) or bool(

        listing.get("is_shopping_offer")

    )

    origin = classify_uk_seller_origin(listing)



    matched = None

    rule = None

    if origin["origin_class"] == _ORIGIN_CONFIRMED:

        matched = origin["hard_evidence"][0] if origin["hard_evidence"] else "confirmed_UK"

        rule = (

            "known_uk_company"

            if origin.get("known_uk_company")

            else "confirmed_UK_hard_evidence"

        )

    elif origin["origin_class"] == _ORIGIN_LIKELY:

        matched = origin["known_retailer"] or "likely_UK"

        rule = "known_retailers_override"

    elif origin["is_marketplace"] and usable_extracted_price(listing) is not None:

        matched = "marketplace_retail"

        rule = "marketplace_unknown_origin"

    elif shopping and usable_extracted_price(listing) is not None and origin["branded_goods"]:

        matched = "branded_retail"

        rule = "branded_goods_unknown_origin"



    if not matched:

        if shopping or str(listing.get("host") or "") == "google.com":

            mer = merchant_name(listing)

            if mer and mer.lower() not in ("unknown", "web result"):

                _unrecognized_merchants.append(

                    {

                        "merchant": mer,

                        "title": str(listing.get("title") or "")[:80],

                        "link": str(listing.get("link") or "")[:120],

                        "product_link_host": product_link_host(listing),

                        "price": listing.get("price"),

                        "extracted_price": listing.get("extracted_price"),

                        "delivery": delivery_text(listing)[:120],

                        "currency": listing.get("currency"),

                        "origin_class": origin["origin_class"],

                        "evidence": origin["evidence"],

                        "branded_goods": origin["branded_goods"],

                        "is_marketplace": origin["is_marketplace"],

                    }

                )

        return None



    priced = usable_extracted_price(listing)

    branded = origin["branded_goods"]

    out = {

        "is_uk_shopping_seller": True,

        "uk_seller_match": matched,

        "uk_seller_rule": rule,

        "uk_seller_label": _LABEL_RETAIL,

        "via_google_shopping": shopping,

        "best_pick_eligible": False,

        "channel": "uk_retail_shopping",

        "price_type": "retail",

        "sourcing_action": "verify_bulk_discount",

        "sourcing_note": _LABEL_RETAIL,

        "uk_origin_class": origin["origin_class"],

        "uk_origin_evidence": origin["evidence"],

        "uk_origin_hard_evidence": origin["hard_evidence"],

        "uk_known_retailer": origin["known_retailer"],

        "uk_known_company": origin.get("known_uk_company"),

        "uk_is_marketplace": origin["is_marketplace"],

        "branded_goods": branded,

        "branded_goods_note": (

            "branded goods; authorized-reseller rules may apply" if branded else None

        ),

        "uk_extracted_price": priced,

        "uk_has_usable_price": priced is not None,

        "uk_review_reason": review_classification_reason(listing),

    }

    if matched in ("marketplace_retail", "branded_retail"):

        out["uk_origin_class"] = _ORIGIN_UNKNOWN

    return out





def annotate_uk_shopping_sellers(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:

    out: list[dict[str, Any]] = []

    for row in listings or []:

        item = dict(row)

        shopping = is_google_shopping_link(str(item.get("link") or "")) or bool(

            item.get("is_shopping_offer")

        ) or str(item.get("host") or "") == "google.com"

        if shopping and not item.get("uk_origin_class"):

            origin = classify_uk_seller_origin(item)

            item["uk_origin_class"] = origin["origin_class"]

            item["uk_origin_evidence"] = origin["evidence"]

            item["uk_origin_hard_evidence"] = origin["hard_evidence"]

            item["uk_known_retailer"] = origin["known_retailer"]

            item["uk_known_company"] = origin.get("known_uk_company")

            item["uk_is_marketplace"] = origin["is_marketplace"]

            item["branded_goods"] = origin["branded_goods"]

            if origin["branded_goods"]:

                item["branded_goods_note"] = (

                    "branded goods; authorized-reseller rules may apply"

                )



        meta = infer_uk_shopping_seller(item)

        if meta:

            item.update(meta)

            item["best_pick_eligible"] = False

            item["price_type"] = "retail"

            priced = meta.get("uk_has_usable_price")

            if priced and meta.get("is_uk_shopping_seller"):

                item["price_review_only"] = False

                item["uk_retail_priced"] = True

                item["counts_as_live_listing"] = False

                item["counts_as_priced_comparison"] = True

                item["is_product_page"] = False

                item["sourcing_note"] = _LABEL_RETAIL

                ext = item.get("extracted_price")

                if ext is not None and (

                    not item.get("price")

                    or re.match(r"^(see listing|n/?a)$", str(item.get("price") or ""), re.I)

                ):

                    cur = str(item.get("currency") or "GBP").upper()

                    try:

                        val = float(ext)

                        item["price"] = f"£{val:g}" if cur == "GBP" else f"{cur} {val:g}"

                    except (TypeError, ValueError):

                        item["price"] = str(ext)

                if not item.get("price_source") or item.get("price_source") in (

                    "rejected_storefront",

                    "shopping_offer_unpriced",

                ):

                    item["price_source"] = "serp_shopping"

            else:

                item["price_review_only"] = True

                item["uk_retail_priced"] = False

                item["counts_as_live_listing"] = False

                item["counts_as_priced_comparison"] = False

        else:

            if not item.get("price_type"):

                item["price_type"] = infer_price_type(item)

        if not item.get("price_type"):

            item["price_type"] = infer_price_type(item)

        out.append(item)

    return out





def annotate_price_types(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:

    out = []

    for row in listings or []:

        item = dict(row)

        if not item.get("price_type"):

            item["price_type"] = infer_price_type(item)

        if item.get("price_type") == "retail":

            item["best_pick_eligible"] = False

            item["sourcing_note"] = item.get("sourcing_note") or _LABEL_RETAIL

        out.append(item)

    return out





def uk_review_row_dump(listing: dict[str, Any]) -> dict[str, Any]:

    origin = {

        "origin_class": listing.get("uk_origin_class"),

        "evidence": listing.get("uk_origin_evidence") or [],

    }

    if not origin["origin_class"]:

        origin = classify_uk_seller_origin(listing)

    return {

        "merchant": merchant_name(listing),

        "product_link_host": product_link_host(listing),

        "price": listing.get("price"),

        "extracted_price": listing.get("extracted_price"),

        "usable_extracted_price": usable_extracted_price(listing),

        "delivery": delivery_text(listing)[:160] or None,

        "currency": listing.get("currency"),

        "price_type": listing.get("price_type") or infer_price_type(listing),

        "why_uk_review": listing.get("uk_review_reason")

        or review_classification_reason(listing),

        "origin_class": origin.get("origin_class") or origin.get("uk_origin_class"),

        "evidence": origin.get("evidence") or origin.get("uk_origin_evidence") or [],

        "known_uk_company": listing.get("uk_known_company")

        or origin.get("known_uk_company"),

        "branded_goods": bool(listing.get("branded_goods")),

        "branded_goods_note": listing.get("branded_goods_note"),

        "is_marketplace": bool(listing.get("uk_is_marketplace")),

        "uk_retail_priced": bool(listing.get("uk_retail_priced")),

        "title": str(listing.get("title") or "")[:80],

        "link": str(listing.get("link") or "")[:120],

    }


