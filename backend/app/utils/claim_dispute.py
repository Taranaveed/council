"""Detect contradictory agent claims about the same seller → disputed facts."""
from __future__ import annotations

import re
from typing import Any


_ADDRESS_RE = re.compile(
    r"(?P<label>(?:address|located\s+at|office\s+at|warehouse\s+at))\s*[:\-]?\s*(?P<val>[^\n.;]{8,120})",
    re.I,
)
_COD_RE = re.compile(r"\b(COD|cash\s+on\s+delivery|no\s+COD)\b", re.I)
_BANK_RE = re.compile(r"\b(bank\s+transfer|wire\s+transfer|IBAN|account\s+number)\b", re.I)


def _norm_claim(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def extract_seller_claims(agent_texts: dict[str, str], *, seller_hint: str = "") -> list[dict[str, Any]]:
    """Pull address/payment claims from agent replies for dispute detection."""
    claims: list[dict[str, Any]] = []
    hint = _norm_claim(seller_hint)
    for agent, raw in (agent_texts or {}).items():
        text = str(raw or "")
        if hint and hint not in _norm_claim(text) and seller_hint:
            # still scan — agents may omit vendor name
            pass
        for m in _ADDRESS_RE.finditer(text):
            claims.append(
                {
                    "agent": agent,
                    "kind": "address",
                    "value": _norm_claim(m.group("val")),
                    "quote": m.group(0).strip()[:160],
                    "fact_id": None,
                }
            )
        for m in _COD_RE.finditer(text):
            claims.append(
                {
                    "agent": agent,
                    "kind": "cod",
                    "value": _norm_claim(m.group(0)),
                    "quote": m.group(0).strip()[:80],
                    "fact_id": None,
                }
            )
        for m in _BANK_RE.finditer(text):
            claims.append(
                {
                    "agent": agent,
                    "kind": "payment",
                    "value": _norm_claim(m.group(0)),
                    "quote": m.group(0).strip()[:80],
                    "fact_id": None,
                }
            )
    return claims


def mark_disputed_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    If two agents assert contradictory values for the same kind, mark both disputed.
    Agreement is NOT verification — only contradictions are flagged.
    """
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for c in claims or []:
        by_kind.setdefault(str(c.get("kind") or "other"), []).append(c)

    disputed_ids: set[int] = set()
    for kind, rows in by_kind.items():
        values = {(r.get("agent"), r.get("value")) for r in rows}
        distinct_vals = {v for _, v in values if v}
        agents = {a for a, _ in values}
        if kind == "address" and len(distinct_vals) >= 2 and len(agents) >= 2:
            for i, r in enumerate(claims):
                if r.get("kind") == kind:
                    disputed_ids.add(i)
        if kind == "cod" and len(distinct_vals) >= 2 and len(agents) >= 2:
            # e.g. "COD" vs "no COD"
            for i, r in enumerate(claims):
                if r.get("kind") == kind:
                    disputed_ids.add(i)

    out: list[dict[str, Any]] = []
    for i, c in enumerate(claims or []):
        item = dict(c)
        if i in disputed_ids:
            item["disputed"] = True
            item["status"] = "disputed"
        else:
            item["disputed"] = False
            item["status"] = "unchecked"
        out.append(item)
    return out


def apply_disputed_to_listings(
    listings: list[dict[str, Any]],
    agent_texts: dict[str, str],
    *,
    winner_link: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Annotate listings with facts_disputed when agents contradict on address/COD."""
    winner = None
    for row in listings or []:
        if winner_link and str(row.get("link") or "") == winner_link:
            winner = row
            break
    if not winner and listings:
        winner = next((x for x in listings if x.get("best_pick")), listings[0])

    seller = str((winner or {}).get("vendor") or (winner or {}).get("source") or "")
    claims = mark_disputed_claims(extract_seller_claims(agent_texts, seller_hint=seller))
    has_disputed = any(c.get("disputed") for c in claims)

    out: list[dict[str, Any]] = []
    for row in listings or []:
        item = dict(row)
        if has_disputed and (
            not winner_link
            or str(item.get("link") or "") == winner_link
            or item.get("best_pick")
        ):
            item["facts_disputed"] = True
            item["disputed_claims"] = [c for c in claims if c.get("disputed")]
        out.append(item)
    return out, claims
