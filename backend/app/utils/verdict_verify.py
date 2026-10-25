"""Verify deal-finder verdict numbers against live listing fact sheet."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.utils.fact_sheet import cite_check_against_sheet
from app.utils.listing_risk import pick_has_blocking_flags
from app.utils.money import parse_money

_INVENTED_CLAIM_RE = re.compile(
    r"(?:"
    r"karachi\s+address|lahore\s+address|street\s+address|"
    r"formal\s+quotation|printable\s+invoice|"
    r"bank\s+transfer\s+with\s+(?:a\s+)?receipt|"
    r"recognized\s+marketplace|meets?\s+safety\s+needs|"
    r"buyer-?rating\s+system|no\s+return\s+policy"
    r")",
    re.I,
)


def _valid_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _amount(raw: Any) -> float | None:
    return parse_money(raw)


def _amounts_close(a: float | None, b: float | None, *, tol: float = 0.08) -> bool:
    if a is None or b is None:
        return False
    if a <= 0 or b <= 0:
        return False
    hi = max(a, b)
    lo = min(a, b)
    return (hi - lo) / hi <= tol or abs(a - b) < 1.0


def _match_listing(winner: dict[str, Any], listings: list[dict[str, Any]]) -> dict[str, Any] | None:
    w_link = _valid_url(winner.get("link"))
    if w_link:
        for row in listings or []:
            if _valid_url(row.get("link")) == w_link:
                return row
    w_title = _norm(winner.get("title"))
    w_vendor = _norm(winner.get("vendor"))
    w_price = _amount(winner.get("price"))
    best = None
    best_score = -1
    for row in listings or []:
        score = 0
        if w_title and _norm(row.get("title")):
            if w_title == _norm(row.get("title")):
                score += 40
            elif w_title in _norm(row.get("title")) or _norm(row.get("title")) in w_title:
                score += 20
        if w_vendor and _norm(row.get("vendor")):
            if w_vendor in _norm(row.get("vendor")) or _norm(row.get("vendor")) in w_vendor:
                score += 25
        if _amounts_close(w_price, _amount(row.get("price"))):
            score += 20
        if row.get("best_pick"):
            score += 5
        if score > best_score:
            best_score = score
            best = row
    return best if best_score >= 20 else None


def clear_best_pick(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in listings or []:
        item = dict(row)
        item["best_pick"] = False
        item.pop("pick_reason", None)
        item.pop("rank_reason", None)
        out.append(item)
    return out


def _scrub_invented(text: str) -> str:
    cleaned = _INVENTED_CLAIM_RE.sub("", str(text or ""))
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ,;.-")


def _set_maybe(out: dict[str, Any], reason: str) -> dict[str, Any]:
    out["verdict"] = "MAYBE"
    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    winner["reason"] = reason
    out["winner"] = winner
    out["summary"] = reason
    return out


def _mark_pick(rows: list[dict[str, Any]], link: str) -> None:
    for row in rows:
        row["best_pick"] = _valid_url(row.get("link")) == _valid_url(link)


def _unit_price_usable(matched: dict[str, Any]) -> tuple[bool, str]:
    """Reject storefront or missing extracted unit prices."""
    link = str(matched.get("link") or "")
    if matched.get("is_product_page") is False or matched.get("unit_price_rejected"):
        return False, "unit price came from a storefront / non-product page"
    src = str(matched.get("price_source") or "").lower()
    if src == "rejected_storefront":
        return False, "unit price rejected (storefront)"
    price = str(matched.get("price") or "").strip()
    if not price or re.match(r"^(see listing|n/?a)$", price, re.I):
        return False, "unit price missing from extracted product data"
    if _amount(price) is None:
        return False, "unit price not parseable on the listing row"
    return True, ""


def verify_verdict_against_listings(
    verdict: dict[str, Any],
    listings: list[dict[str, Any]],
    *,
    landed_cost: dict[str, Any] | None = None,
    risk_flags: list[dict[str, str]] | None = None,
    fact_sheet: dict[str, Any] | None = None,
    budget: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """
    - Ground winner on listing table
    - Reject storefront / missing unit prices
    - Require card ≈ verdict ≈ landed unit
    - Cite-check every money number against the fact sheet
    - Maybe when verdict would flip across the landed low–high range
    - Downgrade BUY → MAYBE on blocking risk flags
    """
    out = dict(verdict or {})
    rows = [dict(x) for x in (listings or [])]
    notes: list[str] = []
    tag = str(out.get("verdict") or "").upper()

    if tag in ("PASS", "SKIP", "NO_MATCH", ""):
        rows = clear_best_pick(rows)
        winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
        winner["reason"] = _scrub_invented(str(winner.get("reason") or ""))
        if tag == "NO_MATCH":
            winner["link"] = ""
            winner["price"] = ""
            winner["title"] = ""
            winner["vendor"] = ""
        out["winner"] = winner
        out["summary"] = _scrub_invented(str(out.get("summary") or ""))
        # Still cite-check PASS prose
        orphans = cite_check_against_sheet(
            [str(winner.get("reason") or ""), str(out.get("summary") or "")],
            fact_sheet,
            landed=landed_cost,
        )
        if orphans and tag != "NO_MATCH":
            notes.append(f"ungrounded numbers on Pass: {', '.join(orphans[:6])}")
        return out, rows, notes

    if not rows:
        out["verdict"] = "PASS"
        winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
        winner["reason"] = "No live listings to verify against — cannot recommend a buy."
        out["winner"] = winner
        out["summary"] = winner["reason"]
        return out, rows, ["empty listings"]

    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    winner["reason"] = _scrub_invented(str(winner.get("reason") or ""))
    out["summary"] = _scrub_invented(str(out.get("summary") or ""))

    matched = _match_listing(winner, rows)
    if not matched:
        notes.append("winner not found in listing table")
        out = _set_maybe(
            out,
            "Maybe, verify — recommended seller was not found in the live listing table.",
        )
        rows = clear_best_pick(rows)
        return out, rows, notes

    usable, reject_reason = _unit_price_usable(matched)
    if not usable:
        notes.append(reject_reason)
        out = _set_maybe(
            out,
            f"Maybe, verify — {reject_reason}. Open a product-detail page with a parseable unit price.",
        )
        _mark_pick(rows, str(matched.get("link") or ""))
        out["winner"] = {
            **dict(out.get("winner") or {}),
            "title": str(matched.get("title") or ""),
            "vendor": str(matched.get("vendor") or matched.get("source") or ""),
            "price": str(matched.get("price") or ""),
            "link": str(matched.get("link") or ""),
        }
        return out, rows, notes

    card_price = str(matched.get("price") or "").strip()
    winner["title"] = str(matched.get("title") or winner.get("title") or "").strip()
    winner["vendor"] = str(
        matched.get("vendor") or matched.get("source") or winner.get("vendor") or ""
    ).strip()
    winner["price"] = card_price
    winner["link"] = str(matched.get("link") or "").strip()

    card_amt = _amount(card_price)
    reason_amt = None
    for m in re.finditer(
        r"(?:Rs\.?\s*|PKR\s*|\$)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:per\s+piece|/pc)",
        str(winner.get("reason") or ""),
        re.I,
    ):
        reason_amt = _amount(m.group(1) or m.group(2))
        if reason_amt:
            break

    landed_unit = None
    if landed_cost and isinstance(landed_cost, dict):
        landed_unit = _amount(landed_cost.get("unit_price")) or _amount(
            landed_cost.get("unit_price_local")
        )

    mismatch = False
    if card_amt and reason_amt and not _amounts_close(card_amt, reason_amt, tol=0.12):
        mismatch = True
        notes.append(f"price disagree: card {card_price} vs verdict text unit ~{reason_amt}")
    if card_amt and landed_unit and not _amounts_close(card_amt, landed_unit, tol=0.12):
        mismatch = True
        notes.append(f"price disagree: card {card_price} vs landed unit ~{landed_unit}")

    if mismatch:
        out = _set_maybe(
            out,
            f"Maybe, verify — prices disagreed across the card ({card_price}), "
            "verdict text, and landed-cost math. Use the listing card price only.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    # Cite-check: every money number in verdict/agents must appear on the fact sheet
    agent = out.get("agent_breakdown") if isinstance(out.get("agent_breakdown"), dict) else {}
    cite_texts = [
        str(winner.get("reason") or ""),
        str(out.get("summary") or ""),
        str(agent.get("thrift_advocate") or ""),
        str(agent.get("risk_analyst") or ""),
        str(agent.get("contextual_persona") or ""),
    ]
    orphans = cite_check_against_sheet(cite_texts, fact_sheet, landed=landed_cost)
    if orphans:
        notes.append(f"numbers not in fact sheet: {', '.join(orphans[:8])}")
        out = _set_maybe(
            out,
            "Maybe, verify — the verdict cited numbers that are not on the listing fact sheet "
            f"({', '.join(orphans[:5])}). Re-check the product page.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    # Flip within assumption range → Maybe
    flips = bool(landed_cost and landed_cost.get("verdict_flips_in_range"))
    if not flips and budget is not None and landed_cost:
        try:
            b = float(budget)
            lo = float(landed_cost.get("range_low_amount") or 0)
            hi = float(landed_cost.get("range_high_amount") or 0)
            if b > 0 and lo > 0 and hi > 0 and lo <= b < hi:
                flips = True
        except (TypeError, ValueError):
            flips = False
    if flips:
        notes.append("verdict flips within landed low–high assumption range")
        lo = landed_cost.get("range_low") if landed_cost else "?"
        hi = landed_cost.get("range_high") if landed_cost else "?"
        out = _set_maybe(
            out,
            f"Maybe, verify — under optimistic assumptions the deal fits (~{lo}), "
            f"but under cautious duty/freight it may not (~{hi}). "
            "Confirm weight, freight, duty, and MOQ on the seller page.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    blocking = pick_has_blocking_flags(risk_flags or [], winner.get("link"))
    high = [f for f in blocking if f.get("severity") == "high"]
    trust = [
        f
        for f in blocking
        if f.get("code") in ("unverified_supplier", "warranty_not_verified", "not_product_page", "spec_missing")
    ]
    if high or len(trust) >= 2 or any(f.get("code") == "not_product_page" for f in blocking):
        issues = ", ".join(sorted({str(f.get("message")) for f in (high or trust)}))
        notes.append(f"blocking flags: {issues}")
        out = _set_maybe(
            out,
            f"Maybe, verify — {issues}. Confirm on the seller page before paying.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    # Missing must-have wired / wireless conflict on the pick → never Buy
    pick_misses = matched.get("spec_misses") if isinstance(matched.get("spec_misses"), list) else []
    wired_miss = matched.get("wired_conflict") or any(
        isinstance(m, dict) and m.get("id") == "wired" for m in pick_misses
    )
    if wired_miss:
        notes.append("pick missing wired / conflicts with wireless")
        wired_ok = [
            r
            for r in rows
            if r.get("spec_ok")
            and not r.get("wired_conflict")
            and not any(
                isinstance(m, dict) and m.get("id") == "wired"
                for m in (r.get("spec_misses") or [])
            )
        ]
        rows = clear_best_pick(rows)
        if not wired_ok:
            out["verdict"] = "NO_MATCH"
            reason = (
                "No good matches — no listing clearly shows wired / 3.5mm "
                "(results look wireless or TWS). Try “wired handsfree earphones 3.5mm wholesale”."
            )
            out["winner"] = {
                "title": "",
                "vendor": "",
                "price": "",
                "link": "",
                "reason": reason,
            }
            out["summary"] = reason
            return out, rows, notes
        # Prefer a wired-ok listing as pick instead of the wireless one
        alt = wired_ok[0]
        out = _set_maybe(
            out,
            "Maybe, verify — the first pick looked wireless/TWS while you asked for wired. "
            f"Check “{str(alt.get('title') or '')[:60]}” for a 3.5mm / aux jack before ordering.",
        )
        _mark_pick(rows, str(alt.get("link") or ""))
        out["winner"] = {
            "title": str(alt.get("title") or ""),
            "vendor": str(alt.get("vendor") or alt.get("source") or ""),
            "price": str(alt.get("price") or ""),
            "link": str(alt.get("link") or ""),
            "reason": out["winner"].get("reason") if isinstance(out.get("winner"), dict) else "",
        }
        return out, rows, notes

    # Unreliable tiers / MOQ not met / disputed facts / over budget → block Buy
    if matched.get("tiers_reliable") is False or (
        landed_cost and landed_cost.get("tiers_reliable") is False
    ):
        notes.append("unreliable price tiers")
        out = _set_maybe(
            out,
            "Maybe, verify — quantity price tiers are unreliable or contradictory; "
            "use the widened range and confirm on the product page.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    if matched.get("moq_not_met") or (landed_cost and landed_cost.get("moq_not_met")):
        notes.append("MOQ not met")
        out = _set_maybe(
            out,
            "Maybe, verify — order quantity is below the seller MOQ; the stated tier price does not apply.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    if matched.get("facts_disputed") or any(
        f.get("code") == "disputed_fact" for f in (risk_flags or [])
    ):
        notes.append("disputed facts")
        out = _set_maybe(
            out,
            "Maybe, verify — agents asserted contradictory facts about this seller; treat claims as disputed.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    if (
        budget is not None
        and landed_cost
        and landed_cost.get("fits_budget_mid") is False
        and landed_cost.get("fits_budget_low") is False
    ):
        notes.append("over budget")
        out = _set_maybe(
            out,
            f"Maybe, verify — mid landed {landed_cost.get('estimated_total')} exceeds budget "
            f"{landed_cost.get('budget_display')}.",
        )
        _mark_pick(rows, winner["link"])
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    if matched.get("unit_price_verified") is False:
        notes.append("unverified price")
        out = _set_maybe(
            out,
            "Maybe, verify — unit price is not page-verified (SERP/snippet only). Confirm on the product page.",
        )
        rows = clear_best_pick(rows)
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    if matched.get("price_outlier") or matched.get("unit_price_unreliable") or matched.get("implausible_metal"):
        notes.append("implausible/outlier price")
        out = _set_maybe(
            out,
            "Maybe, verify — unit price failed plausibility checks (bad scrape or outlier). "
            "Do not treat the card price as a confirmed unit cost.",
        )
        rows = clear_best_pick(rows)
        out["winner"] = {**dict(out.get("winner") or {}), **winner}
        return out, rows, notes

    out["winner"] = winner
    out["verdict"] = "BUY"
    _mark_pick(rows, winner["link"])
    return out, rows, notes
