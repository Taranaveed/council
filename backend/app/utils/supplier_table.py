"""Multi-supplier comparison rows with per-listing risk 1–10."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def _host(link: str | None) -> str:
    try:
        h = urlparse(str(link or "")).hostname or ""
    except Exception:
        return ""
    return h.replace("www.", "").lower()


def listing_risk_1_to_10(row: dict[str, Any], *, is_bulk: bool = False) -> dict[str, Any]:
    """Heuristic risk score for one listing. 1 = safer, 10 = riskiest."""
    score = 3
    reasons: list[str] = []

    if row.get("counts_as_live_listing") is False or row.get("is_product_page") is False:
        score += 3
        reasons.append("Not a clear product page")
    if row.get("unit_price_rejected"):
        score += 2
        reasons.append("Unit price unreliable")
    if row.get("currency_mismatch") or str(row.get("supplier_origin") or "").lower() == "foreign":
        score += 2
        reasons.append("Import / FX / freight risk")
    if is_bulk and not row.get("moq"):
        score += 1
        reasons.append("MOQ not listed")
    host = _host(str(row.get("link") or ""))
    known = str(row.get("vendor_status") or "").lower() in ("known", "known_marketplace", "marketplace")
    if known:
        score -= 1
        reasons.append("Known marketplace host")
    if not host:
        score += 2
        reasons.append("Missing link")
    if re.search(r"whatsapp|telegram|bit\.ly|tinyurl", host):
        score += 3
        reasons.append("Chat / short-link host")

    score = max(1, min(10, score))
    if not reasons:
        reasons.append("Baseline listing risk")
    return {"score": score, "reasons": reasons[:4]}


def landed_mid_display(row: dict[str, Any]) -> str:
    """
    Single source of truth for table / brief: listing.landed_cost from compute_landed_cost.
    If missing → 'needs quote'.
    """
    landed = row.get("landed_cost") if isinstance(row.get("landed_cost"), dict) else None
    if not landed:
        return "needs quote"
    mid = landed.get("estimated_total") or landed.get("mid")
    if not mid:
        return "needs quote"
    label = str(mid)
    if landed.get("duty_fallback"):
        label = f"{label} (estimated, not a tariff lookup)"
    if landed.get("fx_fallback"):
        label = f"{label} (estimated, not a live FX quote)"
    return label


def build_supplier_table(
    listings: list[dict[str, Any]],
    *,
    verdict: dict[str, Any] | None = None,
    quantity: int | None = None,
    is_bulk: bool = False,
    limit: int = 8,
) -> list[dict[str, Any]]:
    verdict = verdict if isinstance(verdict, dict) else {}
    tag = str(verdict.get("verdict") or "").upper()
    allow_best = tag in ("BUY", "MAYBE")
    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    winner_link = str(winner.get("link") or "") if allow_best else ""

    rows: list[dict[str, Any]] = []
    for i, raw in enumerate((listings or [])[:limit]):
        if not isinstance(raw, dict):
            continue
        link = str(raw.get("link") or "")
        risk = listing_risk_1_to_10(raw, is_bulk=is_bulk)
        is_winner = allow_best and (
            bool(raw.get("best_pick")) or (bool(winner_link) and link == winner_link)
        )
        origin = str(raw.get("supplier_origin") or "").lower()
        if not origin:
            lc = raw.get("landed_cost") if isinstance(raw.get("landed_cost"), dict) else {}
            origin = str(lc.get("origin_country") or "").lower() or (
                "foreign" if raw.get("currency_mismatch") else "local"
            )
        landed = raw.get("landed_cost") if isinstance(raw.get("landed_cost"), dict) else None
        rows.append(
            {
                "rank": i + 1,
                "vendor": raw.get("vendor") or _host(link) or "Seller",
                "title": raw.get("title") or "",
                "link": link,
                "unit_price": raw.get("price_local_approx") or raw.get("price") or "",
                "currency": raw.get("currency") or "",
                "moq": raw.get("moq"),
                "origin": origin,
                "risk_score": risk["score"],
                "risk_reasons": risk["reasons"],
                "landed_mid": landed_mid_display(raw),
                "landed_cost": landed,
                "duty_fallback": bool(landed.get("duty_fallback")) if landed else False,
                "best_pick": bool(is_winner),
                "vendor_status": raw.get("vendor_status"),
            }
        )
    return rows


def build_negotiation_message(
    *,
    item_name: str,
    quantity: int | None,
    verdict: dict[str, Any],
    questions: list[str],
    location: str | None = None,
) -> str | None:
    tag = str(verdict.get("verdict") or "").upper()
    if tag not in ("BUY", "MAYBE"):
        return None
    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    vendor = str(winner.get("vendor") or "Seller").strip()
    title = str(winner.get("title") or item_name).strip()
    price = str(winner.get("price") or "").strip()
    qty = quantity if isinstance(quantity, int) and quantity >= 1 else None

    lines = [
        f"Hi {vendor},",
        "",
        f"I'm looking at: {title}.",
    ]
    if price:
        lines.append(f"Listed price I'm seeing: {price}.")
    if qty:
        lines.append(f"I want about {qty} units for restock ({location or 'my market'}).")
    else:
        lines.append(f"This is for restock in {location or 'my market'}.")
    lines.append("")
    lines.append("Before I order, please confirm:")
    qs = [q for q in (questions or []) if str(q).strip()][:4]
    if not qs:
        qs = [
            "What is your MOQ and unit price for my quantity?",
            "How much stock is ready now, and what is the lead time?",
            "What payment terms do you offer, and can I order a sample first?",
        ]
    for i, q in enumerate(qs, 1):
        lines.append(f"{i}. {q}")
    lines.extend(["", "Thanks,"])
    return "\n".join(lines)


def build_brief_export_text(
    *,
    item_name: str,
    location: str | None,
    quantity: int | None,
    buying_mode: str | None,
    verdict: dict[str, Any],
    supplier_table: list[dict[str, Any]],
    negotiation_message: str | None,
    brief_id: int | None = None,
    share_url: str | None = None,
) -> str:
    tag = str(verdict.get("verdict") or "").upper()
    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    landed = verdict.get("landed_cost") if isinstance(verdict.get("landed_cost"), dict) else {}
    lines = [
        "COUNCIL — DEAL BRIEF",
        "=" * 40,
        f"Item: {item_name}",
        f"Location: {location or '—'}",
        f"Quantity: {quantity or '—'}",
        f"Mode: {buying_mode or 'retail'}",
        f"Verdict: {tag or '—'}",
    ]
    if brief_id is not None:
        lines.append(f"Brief ID: {brief_id}")
    if share_url:
        lines.append(f"Share: {share_url}")
    lines.append("")
    if winner and (winner.get("link") or winner.get("title") or winner.get("vendor")):
        lines.append(f"Winner: {winner.get('title') or '—'}")
        lines.append(f"Vendor: {winner.get('vendor') or '—'} · {winner.get('price') or '—'}")
        if winner.get("link"):
            lines.append(f"Link: {winner.get('link')}")
    if landed.get("estimated_total") or landed.get("formula"):
        lines.append("")
        lines.append("Landed cost (checkable):")
        mid = landed.get("estimated_total")
        if mid:
            suffix = ""
            if landed.get("duty_fallback"):
                suffix += " (estimated, not a tariff lookup)"
            if landed.get("fx_fallback"):
                suffix += " (estimated, not a live FX quote)"
            lines.append(f"  Mid: {mid}{suffix}")
        if landed.get("formula"):
            lines.append(f"  Formula: {landed.get('formula')}")
        # Prefer weight / freight-derivation / duty-base lines in the brief
        assumptions = list(landed.get("assumptions") or [])
        prefer = [
            a
            for a in assumptions
            if re.search(
                r"^(Weight:|Freight|Freight derivation:|Duty:|FX:|Import VAT:)",
                str(a),
            )
        ]
        rest = [a for a in assumptions if a not in prefer]
        for a in (prefer + rest)[:8]:
            lines.append(f"  - {a}")
    if supplier_table:
        lines.append("")
        lines.append("Supplier comparison:")
        for r in supplier_table:
            pick = " ★" if r.get("best_pick") else ""
            lines.append(
                f"  {r.get('rank')}. {r.get('vendor')}{pick} | {r.get('unit_price') or 'n/a'} | "
                f"MOQ {r.get('moq') or '—'} | {r.get('origin')} | "
                f"risk {r.get('risk_score')}/10 | landed {r.get('landed_mid') or 'needs quote'}"
            )
            if r.get("link"):
                lines.append(f"     {r.get('link')}")
    if negotiation_message:
        lines.append("")
        lines.append("Negotiation message:")
        lines.append(negotiation_message)
    lines.extend(
        [
            "",
            "—",
            "Council ranks live listings. It does not verify sellers, customs, or stock.",
        ]
    )
    return "\n".join(lines)
