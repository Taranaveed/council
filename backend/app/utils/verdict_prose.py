"""Template verdict prose + number consistency validator."""
from __future__ import annotations

import re
from typing import Any

from app.utils.money import parse_money

_NUM_RE = re.compile(
    r"(?:Rs\.?\s*|PKR\s*|\$|€|£|₹)?\s*([\d]{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)",
    re.I,
)


def _amounts_in(text: str) -> list[float]:
    out: list[float] = []
    for m in _NUM_RE.finditer(str(text or "")):
        n = parse_money(m.group(1))
        if n is not None and n >= 1:
            out.append(n)
    return out


def _close(a: float, b: float, tol: float = 0.08) -> bool:
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tol or abs(a - b) < 1.0


def validate_prose_numbers(
    prose: str,
    *,
    card_price: str | None,
    landed: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Every money-like number in prose must appear in card or landed fields."""
    allowed: list[float] = []
    for raw in (
        card_price,
        (landed or {}).get("unit_price"),
        (landed or {}).get("unit_price_local"),
        (landed or {}).get("line_total"),
        (landed or {}).get("estimated_total"),
        (landed or {}).get("range_low"),
        (landed or {}).get("range_high"),
        (landed or {}).get("duty_amount"),
        (landed or {}).get("shipping_amount"),
        (landed or {}).get("budget_display"),
        (landed or {}).get("cost_vs_budget"),
        (landed or {}).get("max_units_note"),
        (landed or {}).get("formula"),
    ):
        n = parse_money(raw)
        if n is not None:
            allowed.append(n)
        # Also pull every money token out of long assumption strings
        if isinstance(raw, str) and len(raw) > 12:
            for m in _NUM_RE.finditer(raw):
                nn = parse_money(m.group(1))
                if nn is not None:
                    allowed.append(nn)
    for key in ("quantity", "moq", "max_units_that_fit", "duty_rate"):
        v = (landed or {}).get(key)
        if isinstance(v, (int, float)) and v > 0:
            if key == "duty_rate" and v <= 1:
                allowed.append(float(int(round(v * 100))))
            else:
                allowed.append(float(v))

    orphans: list[str] = []
    for n in _amounts_in(prose):
        if n < 10 and not re.search(rf"(?:Rs\.?|PKR|\$)\s*{re.escape(str(int(n)))}", prose, re.I):
            # bare small integers (counts) ok if qty/moq
            if any(_close(n, a, tol=0.01) for a in allowed):
                continue
            continue
        if not any(_close(n, a) for a in allowed):
            orphans.append(str(int(n) if n == int(n) else n))
    return len(orphans) == 0, orphans


def build_verdict_prose(
    *,
    tag: str,
    winner: dict[str, Any] | None,
    landed: dict[str, Any] | None,
    budget: float | None = None,
) -> str:
    """Deterministic template — no invented figures."""
    w = winner if isinstance(winner, dict) else {}
    vendor = str(w.get("vendor") or "Seller").strip() or "Seller"
    price = str(w.get("price") or "").strip()
    title = str(w.get("title") or "").strip()
    t = (tag or "").upper()

    if t == "NO_MATCH":
        return (
            "No good matches — fewer than 2 relevant product-detail listings with a parseable "
            "unit price. Refine your query."
        )
    if t in ("PASS", "SKIP"):
        return "Skip — no Best pick. Open product-detail links yourself to verify MOQ and price."

    bits = []
    if t == "MAYBE":
        bits.append("Maybe, verify")
    else:
        bits.append("Buy")
    if vendor and price:
        bits.append(f"{vendor} at {price}")
    elif title:
        bits.append(title)
    if landed:
        if landed.get("estimated_total"):
            bits.append(f"mid landed {landed['estimated_total']}")
        if landed.get("range_low") and landed.get("range_high"):
            bits.append(f"range {landed['range_low']}–{landed['range_high']}")
        if landed.get("cost_vs_budget"):
            bits.append(str(landed["cost_vs_budget"]))
        elif budget is None:
            bits.append("no budget set")
        if landed.get("max_units_that_fit") is not None:
            bits.append(f"max units that fit: {landed['max_units_that_fit']}")
        if landed.get("moq_not_met"):
            bits.append("MOQ not met for the stated tier")
        if landed.get("freight_dominates_warning"):
            bits.append("freight/weight assumption dominates landed cost")
    return ". ".join(bits) + "."


def apply_verified_prose(
    verdict: dict[str, Any],
    *,
    landed: dict[str, Any] | None,
    budget: float | None = None,
) -> dict[str, Any]:
    out = dict(verdict or {})
    tag = str(out.get("verdict") or "").upper()
    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    prose = build_verdict_prose(tag=tag, winner=winner, landed=landed, budget=budget)
    ok, orphans = validate_prose_numbers(prose, card_price=winner.get("price"), landed=landed)
    if not ok:
        # regenerate once from template only (already template) — strip orphans by rebuild
        prose = build_verdict_prose(tag=tag, winner=winner, landed=landed, budget=budget)
        ok2, orphans2 = validate_prose_numbers(prose, card_price=winner.get("price"), landed=landed)
        if not ok2:
            prose = (
                f"{tag.title().replace('_', ' ')} — use card price {winner.get('price') or 'n/a'}"
                + (
                    f" and landed {landed.get('estimated_total')}"
                    if landed and landed.get("estimated_total")
                    else ""
                )
                + "."
            )
            out["prose_validation"] = {"ok": False, "orphans": orphans2}
        else:
            out["prose_validation"] = {"ok": True, "orphans": []}
    else:
        out["prose_validation"] = {"ok": True, "orphans": []}

    # Also validate any LLM reason; replace if it fails
    existing = str(winner.get("reason") or "")
    if existing:
        e_ok, e_orphans = validate_prose_numbers(
            existing, card_price=winner.get("price"), landed=landed
        )
        if not e_ok:
            winner["reason"] = prose
            out["prose_validation"] = {
                "ok": False,
                "orphans": e_orphans,
                "replaced_llm_reason": True,
            }
        # else keep LLM reason if consistent
    else:
        winner["reason"] = prose

    if not str(out.get("summary") or "").strip():
        out["summary"] = winner.get("reason") or prose
    else:
        s_ok, _ = validate_prose_numbers(
            str(out.get("summary")), card_price=winner.get("price"), landed=landed
        )
        if not s_ok:
            out["summary"] = winner.get("reason") or prose
    out["winner"] = winner
    return out
