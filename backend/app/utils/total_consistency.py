"""Cross-check agent-written landed totals against the calculator."""
from __future__ import annotations

import re
from typing import Any

from app.utils.money import parse_money

_TOTAL_HINT_RE = re.compile(
    r"(?:landed|total|all[- ]?in|cif\+duty|duty\+freight|approx(?:imate(?:ly)?)?|"
    r"around|about|roughly|≈|~)\s*"
    r"(?:cost\s*(?:of|is|=|:)?\s*)?"
    r"(?:Rs\.?|PKR|\$|USD|₹|INR)?\s*"
    r"([\d]{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)",
    re.I,
)
_MONEY_RE = re.compile(
    r"(?:Rs\.?|PKR)\s*([\d]{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)"
    r"|\$\s*([\d]{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)",
    re.I,
)


def extract_agent_totals(transcript: dict[str, str] | None) -> list[dict[str, Any]]:
    """Pull large money amounts that look like order totals from agent prose."""
    found: list[dict[str, Any]] = []
    for agent, text in (transcript or {}).items():
        t = str(text or "")
        for m in _TOTAL_HINT_RE.finditer(t):
            n = parse_money(m.group(1))
            if n is not None and n >= 500:
                found.append({"agent": agent, "amount": float(n), "quote": m.group(0).strip()[:80]})
        # Also catch bare Rs 200,000-style near 'total'/'landed' windows
        for m in _MONEY_RE.finditer(t):
            raw = m.group(1) or m.group(2)
            n = parse_money(raw)
            if n is None or n < 5000:
                continue
            window = t[max(0, m.start() - 40) : m.end() + 20].lower()
            if any(k in window for k in ("landed", "total", "all-in", "all in", "≈", "approx")):
                found.append({"agent": agent, "amount": float(n), "quote": m.group(0).strip()[:80]})
    # Dedupe by agent+rounded amount
    seen: set[tuple[str, int]] = set()
    out: list[dict[str, Any]] = []
    for row in found:
        key = (str(row["agent"]), int(round(row["amount"])))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def check_totals_consistency(
    landed: dict[str, Any] | None,
    transcript: dict[str, str] | None,
    *,
    tolerance: float = 0.15,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """
    If agent-written totals diverge >tolerance from calculator mid/range,
    annotate transcript with a forced caveat and return a consistency report.
    Does not invent new numbers — calculator remains source of truth.
    """
    notes: list[str] = []
    out_tx = dict(transcript or {})
    report: dict[str, Any] = {
        "ok": True,
        "tolerance": tolerance,
        "agent_totals": [],
        "divergences": [],
    }
    if not landed or not isinstance(landed, dict):
        return report, out_tx, notes

    mid = parse_money(landed.get("estimated_total")) or parse_money(
        landed.get("estimated_total_amount")
    )
    lo = parse_money(landed.get("range_low")) or float(landed.get("range_low_amount") or 0) or None
    hi = parse_money(landed.get("range_high")) or float(landed.get("range_high_amount") or 0) or None
    if isinstance(landed.get("estimated_total_amount"), (int, float)):
        mid = float(landed["estimated_total_amount"])
    if isinstance(landed.get("range_low_amount"), (int, float)) and landed["range_low_amount"]:
        lo = float(landed["range_low_amount"])
    if isinstance(landed.get("range_high_amount"), (int, float)) and landed["range_high_amount"]:
        hi = float(landed["range_high_amount"])

    if mid is None or mid <= 0:
        return report, out_tx, notes

    report["calculator_mid"] = mid
    report["calculator_range"] = [lo, hi]
    agent_totals = extract_agent_totals(out_tx)
    report["agent_totals"] = agent_totals

    divergences: list[dict[str, Any]] = []
    for row in agent_totals:
        amt = float(row["amount"])
        # Within calculator range → OK
        if lo and hi and lo > 0 and hi > 0 and lo <= amt <= hi * 1.05:
            continue
        # Within tolerance of mid → OK
        if abs(amt - mid) / max(amt, mid) <= tolerance:
            continue
        divergences.append({**row, "vs_mid_ratio": round(amt / mid, 2)})

    report["divergences"] = divergences
    if not divergences:
        return report, out_tx, notes

    report["ok"] = False
    notes.append("totals_inconsistent")
    calc_disp = str(landed.get("estimated_total") or mid)
    range_disp = ""
    if landed.get("range_low") and landed.get("range_high"):
        range_disp = f" (range {landed['range_low']}–{landed['range_high']})"
    caveat = (
        f" [Consistency note: ignore any order-total figures above that disagree with the "
        f"shared calculator — authoritative mid landed is {calc_disp}{range_disp}. "
        f"Those earlier totals used a different unit basis and must not be relied on.]"
    )
    touched: set[str] = set()
    for d in divergences:
        agent = str(d.get("agent") or "")
        if not agent or agent in touched:
            continue
        text = str(out_tx.get(agent) or "")
        if text and caveat not in text:
            out_tx[agent] = text.rstrip() + caveat
            touched.add(agent)
            notes.append(f"totals_caveat:{agent}")
    return report, out_tx, notes
