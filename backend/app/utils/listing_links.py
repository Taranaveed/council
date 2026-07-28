"""Attach real listing URLs onto deal-finder verdicts (never invent links)."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


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
                "vendor_status": str(item.get("vendor_status") or "Unverified").strip(),
                "note": "",
            }
        )
    return rows


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
    as every listing with a URL (title, vendor, price, link, note).
    """
    out = dict(verdict or {})
    rows = _listing_rows(listings)
    with_links = [r for r in rows if r["link"]]
    if not with_links and not rows:
        return out

    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    pool = with_links or rows

    best = None
    best_score = -1
    for row in pool:
        score = _score_match(winner, row)
        if score > best_score:
            best_score = score
            best = row

    if best and (best_score >= 20 or not _valid_http_url(winner.get("link"))):
        if not str(winner.get("title") or "").strip():
            winner["title"] = best["title"]
        if not str(winner.get("vendor") or "").strip():
            winner["vendor"] = best["vendor"]
        if not str(winner.get("price") or "").strip():
            winner["price"] = best["price"]
        if best["link"]:
            winner["link"] = best["link"]
        out["winner"] = winner

    winner_link = _valid_http_url((out.get("winner") or {}).get("link") if isinstance(out.get("winner"), dict) else "")
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
                    "Verified seller"
                    if row["vendor_status"].lower() == "verified"
                    else "Open listing to check stock / MOQ"
                ),
            }
        )

    # Keep judge notes when they add signal, but always prefer linked rows.
    existing = out.get("alternatives") if isinstance(out.get("alternatives"), list) else []
    for alt in existing:
        if not isinstance(alt, dict):
            continue
        link = _valid_http_url(alt.get("link"))
        vendor = str(alt.get("vendor") or "").strip()
        if not link and not vendor:
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
    return out
