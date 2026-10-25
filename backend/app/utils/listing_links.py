"""Attach real listing URLs onto deal-finder verdicts (never invent links)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.utils.vendor_check import is_known_marketplace_status

_INVENTED_STAT_RE = re.compile(
    r"(?:\d{2,3}\s*%\+?\s*(?:positive\s+)?(?:feedback|rating|reviews?)|"
    r"\d+\+?\s+years?\s+(?:in business|on (?:the )?(?:platform|site)|history)|"
    r"HS\s*codes?\s*[:#]?\s*[\d.]+|"
    r"customs?\s+(?:duty|duties|tax)?\s*(?:of\s*)?\d+(?:\.\d+)?\s*%)",
    re.I,
)

# Prose claims that never appear in Serp snippets — scrub or force a factory disclaimer.
_UNGROUNDED_LANDED_RE = re.compile(
    r"(?:"
    r"\bDDP\b|"
    r"landed\s+cost|"
    r"after\s+dut(?:y|ies)(?:\s*/\s*tax|\s+and\s+tax|\s*/\s*taxes?)?|"
    r"duties?\s*/\s*tax(?:es)?|"
    r"including\s+(?:duties?|customs|shipping|tax(?:es)?)|"
    r"(?:fits?|meets?|under|within)\s+(?:the\s+)?(?:Rs\.?\s*)?(?:budget|ceiling)\s+after|"
    r"local\s+contact|"
    r"return\s+policy|"
    r"provides?\s+local\s+contact|"
    r"karachi\s+address|lahore\s+address|street\s+address|"
    r"formal\s+quotation|printable\s+invoice|"
    r"bank\s+transfer\s+with\s+(?:a\s+)?receipt|"
    r"recognized\s+marketplace|meets?\s+safety\s+needs|"
    r"buyer-?rating\s+system"
    r")",
    re.I,
)

_FACTORY_HOST_RE = re.compile(
    r"alibaba\.|made-in-china\.|dhgate\.|globalsources\.|aliexpress\.|1688\.",
    re.I,
)

_FACTORY_DISCLAIMER = (
    "Factory/wholesale quote only — not landed cost. "
    "Confirm MOQ, shipping, duties, and returns on the seller page before paying."
)


def _valid_http_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return text


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _listing_rows(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in listings or []:
        link = _valid_http_url(item.get("link"))
        rows.append(
            {
                "title": str(item.get("title") or "").strip(),
                "vendor": str(item.get("vendor") or item.get("source") or "Unknown").strip(),
                "price": str(item.get("price") or "").strip(),
                "link": link,
                "vendor_status": str(item.get("vendor_status") or "Unknown").strip(),
                "note": "",
            }
        )
    return rows


def _listings_blob(listings: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in listings or []:
        parts.extend(
            [
                str(item.get("title") or ""),
                str(item.get("vendor") or ""),
                str(item.get("price") or ""),
                str(item.get("pick_reason") or ""),
            ]
        )
    return " ".join(parts).lower()


def _strip_ungrounded_stats(text: str, listings_blob: str) -> str:
    raw = str(text or "")
    if not raw:
        return raw

    def repl(match: re.Match[str]) -> str:
        phrase = match.group(0)
        if phrase.lower() in listings_blob:
            return phrase
        return ""

    cleaned = _INVENTED_STAT_RE.sub(repl, raw)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ,;.-")


def _listing_is_factory(item: dict[str, Any]) -> bool:
    link = str(item.get("link") or "")
    origin = str(item.get("supplier_origin") or "").upper()
    if origin == "CN":
        return True
    if _FACTORY_HOST_RE.search(link):
        return True
    stype = str(item.get("supplier_type") or "").lower()
    if stype in ("factory", "wholesale", "small-lot") and (
        bool(item.get("wholesale")) or _FACTORY_HOST_RE.search(link)
    ):
        return True
    return bool(item.get("wholesale")) and _FACTORY_HOST_RE.search(link) is not None


def _winner_is_factory_quote(verdict: dict[str, Any], listings: list[dict[str, Any]]) -> bool:
    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    w_link = _valid_http_url(winner.get("link"))
    if w_link and _FACTORY_HOST_RE.search(w_link):
        return True
    for item in listings or []:
        if item.get("best_pick") and _listing_is_factory(item):
            return True
        if w_link and _valid_http_url(item.get("link")) == w_link:
            return _listing_is_factory(item)
    return any(_listing_is_factory(item) for item in (listings or [])[:3])


def _sanitize_reason_text(text: str, listings_blob: str, *, force_factory_disclaimer: bool) -> str:
    cleaned = _strip_ungrounded_stats(text, listings_blob)
    if force_factory_disclaimer or _UNGROUNDED_LANDED_RE.search(cleaned):
        return _FACTORY_DISCLAIMER
    return cleaned


def strip_ungrounded_claims(
    verdict: dict[str, Any],
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Remove invented ratings / HS codes / customs % / landed-cost prose not in live listings."""
    out = dict(verdict or {})
    blob = _listings_blob(listings)
    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    if winner:
        winner["reason"] = _sanitize_reason_text(
            str(winner.get("reason") or ""),
            blob,
            force_factory_disclaimer=False,
        )
        out["winner"] = winner
    out["summary"] = _sanitize_reason_text(
        str(out.get("summary") or ""),
        blob,
        force_factory_disclaimer=False,
    )
    return out


def apply_high_risk_bulk_guard(
    verdict: dict[str, Any],
    listings: list[dict[str, Any]],
    risk_score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Keep BUY allowed for contactable factory quotes, but never leave a landed-cost story
    when Risk Analyst already flagged customs/shipping (typical cross-border bulk).
    """
    out = strip_ungrounded_claims(verdict, listings)
    score = int((risk_score or {}).get("score") or 0)
    if score < 2:
        return out
    if str(out.get("verdict") or "").upper() != "BUY":
        return out
    if not _winner_is_factory_quote(out, listings):
        return out
    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    winner["reason"] = _FACTORY_DISCLAIMER
    out["winner"] = winner
    out["summary"] = _FACTORY_DISCLAIMER
    return out


def _score_match(winner: dict[str, Any], row: dict[str, Any]) -> int:
    score = 0
    w_vendor = _norm(winner.get("vendor"))
    w_title = _norm(winner.get("title"))
    w_price = _norm(winner.get("price"))
    w_link = _valid_http_url(winner.get("link"))
    r_vendor = _norm(row.get("vendor"))
    r_title = _norm(row.get("title"))
    r_price = _norm(row.get("price"))
    r_link = _valid_http_url(row.get("link"))

    if w_link and r_link and w_link == r_link:
        return 100
    if w_vendor and r_vendor and (w_vendor in r_vendor or r_vendor in w_vendor):
        score += 40
    if w_title and r_title:
        if w_title == r_title:
            score += 40
        elif w_title in r_title or r_title in w_title:
            score += 25
        else:
            w_tokens = set(w_title.split())
            r_tokens = set(r_title.split())
            overlap = len(w_tokens & r_tokens)
            if overlap >= 2:
                score += 15
    if w_price and r_price and w_price == r_price:
        score += 20
    return score


def attach_listing_links(
    verdict: dict[str, Any],
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Force winner.link from matched live listings and rebuild alternatives
    as every listing with a URL. Invented https URLs not in the live set are dropped.
    """
    out = dict(verdict or {})
    rows = _listing_rows(listings)
    with_links = [r for r in rows if r["link"]]
    listing_urls = {r["link"] for r in with_links}
    if not with_links and not rows:
        return out

    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    pool = with_links or rows

    best = None
    best_score = -1
    for row in pool:
        score = _score_match(winner, row)
        if listings:
            src = next(
                (
                    item
                    for item in listings
                    if _valid_http_url(item.get("link")) == row["link"]
                ),
                None,
            )
            if src and src.get("best_pick"):
                score += 50
        if score > best_score:
            best_score = score
            best = row

    winner_link = _valid_http_url(winner.get("link"))
    if winner_link and winner_link not in listing_urls:
        winner_link = ""
        winner["link"] = ""

    if best and (best_score >= 20 or not winner_link):
        if (not str(winner.get("title") or "").strip() or not winner_link) and best["title"]:
            winner["title"] = best["title"]
        if (not str(winner.get("vendor") or "").strip() or not winner_link) and best["vendor"]:
            winner["vendor"] = best["vendor"]
        if (not str(winner.get("price") or "").strip() or not winner_link) and best["price"]:
            winner["price"] = best["price"]
        if best["link"]:
            winner["link"] = best["link"]
        out["winner"] = winner

    winner_link = _valid_http_url(
        (out.get("winner") or {}).get("link") if isinstance(out.get("winner"), dict) else ""
    )
    alternatives: list[dict[str, Any]] = []
    for row in with_links or rows:
        if winner_link and row["link"] == winner_link:
            continue
        alternatives.append(
            {
                "title": row["title"],
                "vendor": row["vendor"],
                "price": row["price"] or "—",
                "link": row["link"],
                "vendor_status": row["vendor_status"],
                "note": row["note"]
                or (
                    "Known marketplace listing"
                    if is_known_marketplace_status(row["vendor_status"])
                    else "Open listing to check stock / MOQ"
                ),
            }
        )

    existing = out.get("alternatives") if isinstance(out.get("alternatives"), list) else []
    for alt in existing:
        if not isinstance(alt, dict):
            continue
        link = _valid_http_url(alt.get("link"))
        vendor = str(alt.get("vendor") or "").strip()
        if not link and not vendor:
            continue
        if link and link not in listing_urls:
            continue
        already = False
        for row in alternatives:
            if link and row.get("link") == link:
                if alt.get("note") and not row.get("note"):
                    row["note"] = str(alt.get("note"))
                already = True
                break
            if vendor and _norm(row.get("vendor")) == _norm(vendor) and not link:
                if alt.get("note"):
                    row["note"] = str(alt.get("note"))
                already = True
                break
        if already:
            continue
        if link:
            alternatives.append(
                {
                    "title": str(alt.get("title") or "").strip(),
                    "vendor": vendor or "Seller",
                    "price": str(alt.get("price") or "—").strip(),
                    "link": link,
                    "vendor_status": str(alt.get("vendor_status") or ""),
                    "note": str(alt.get("note") or "").strip(),
                }
            )

    out["alternatives"] = alternatives
    return strip_ungrounded_claims(out, listings)


def coerce_verdict_when_listings_exist(
    verdict: dict[str, Any],
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    If the judge claimed listings were missing while live offers exist, ground the
    winner on a real row. Do not force BUY on unpriced or unlinkable junk, and do
    not override a genuine PASS (over budget / unsafe / wrong product).
    """
    if not listings:
        return verdict
    out = dict(verdict or {})
    winner = out.get("winner") if isinstance(out.get("winner"), dict) else {}
    blob = " ".join(
        [
            str(out.get("verdict") or ""),
            str(out.get("summary") or ""),
            str(winner.get("reason") or ""),
        ]
    ).lower()
    empty_claim = any(
        phrase in blob
        for phrase in (
            "no live listing",
            "no listings",
            "listings were supplied",
            "no substantive",
            "no basis to recommend",
            "no basis to evaluate",
            "data outage",
            "empty sync",
            "empty debate",
            "zero listings",
            "cannot evaluate",
        )
    )
    pick = next((item for item in listings if item.get("best_pick")), listings[0])
    pick_link = _valid_http_url(pick.get("link"))
    pick_price = str(pick.get("price") or "").strip()
    if str(out.get("verdict") or "").upper() == "PASS" and empty_claim:
        grounded = {
            "title": str(pick.get("title") or "").strip(),
            "vendor": str(pick.get("vendor") or pick.get("source") or "Supplier").strip(),
            "price": pick_price,
            "link": pick_link,
            "reason": str(
                pick.get("pick_reason")
                or "Live listing was available. Confirm stock, shipping, and payment terms on the seller page before paying."
            ),
        }
        out["winner"] = grounded
        if pick_link and pick_price:
            # Prefer MAYBE when the pick is not a product-detail URL
            link_l = pick_link.lower()
            is_product = bool(
                re.search(
                    r"/product-detail/|/products?/|/proddetail|/item/|/itm/|/dp/",
                    link_l,
                )
            )
            out["verdict"] = "BUY" if is_product else "MAYBE"
            out["summary"] = (
                f"Best cheap pick from live listings: {grounded['vendor']} "
                f"at {grounded['price']}. "
                + (
                    "Open the seller page to confirm MOQ, shipping, and payment — we do not invent landed cost."
                    if is_product
                    else "URL looks like a storefront — open a product page and verify unit price before paying."
                )
            )
        else:
            out["verdict"] = "PASS"
            out["summary"] = (
                "Live listings were returned, but none had both a usable price and an openable URL. "
                "Use the Sellers list — we will not invent a buy price."
            )
    return attach_listing_links(out, listings)
