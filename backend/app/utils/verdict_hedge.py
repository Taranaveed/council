"""Keep verdict confidence language from exceeding agent hedging."""
from __future__ import annotations

import re
from typing import Any

_OVERCLAIM_RE = [
    (re.compile(r"\bthe safest\b", re.I), "a relatively safer"),
    (re.compile(r"\bsafest bulk choice\b", re.I), "marginally safer bulk option"),
    (re.compile(r"\bclearly safe\b", re.I), "not fully verified"),
    (re.compile(r"\bfully safe\b", re.I), "not fully verified"),
    (re.compile(r"\bno risk\b", re.I), "residual risk remains"),
    (re.compile(r"\bguaranteed\b", re.I), "not guaranteed"),
    (re.compile(r"\bbest and safest\b", re.I), "a possible pick with remaining risk"),
]

_HEDGE_MARKERS = re.compile(
    r"\b(marginal(?:ly)?|not fully|partial(?:ly)?|somewhat|cautious|"
    r"verify|unverified|residual|still risky|hedge)\b",
    re.I,
)


def agents_hedge_on_pick(transcript: dict[str, str] | None) -> bool:
    risk = str((transcript or {}).get("risk_analyst") or "")
    persona = str((transcript or {}).get("contextual_persona") or "")
    blob = f"{risk}\n{persona}"
    return bool(_HEDGE_MARKERS.search(blob))


def hedge_verdict_confidence(
    verdict: dict[str, Any],
    transcript: dict[str, str] | None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Soften verdict summary/reason when agents hedged but the judge overclaimed.
    Never upgrades confidence — only downgrades language.
    """
    out = dict(verdict or {})
    notes: list[str] = []
    if not agents_hedge_on_pick(transcript):
        return out, notes

    changed = False
    for field in ("summary",):
        text = str(out.get(field) or "")
        new = text
        for pat, repl in _OVERCLAIM_RE:
            new = pat.sub(repl, new)
        if new != text:
            out[field] = new
            changed = True

    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    reason = str(winner.get("reason") or "")
    new_reason = reason
    for pat, repl in _OVERCLAIM_RE:
        new_reason = pat.sub(repl, new_reason)
    if new_reason != reason:
        winner["reason"] = new_reason
        out["winner"] = winner
        if not str(out.get("summary") or "").strip():
            out["summary"] = new_reason
        changed = True

    tag = str(out.get("verdict") or "").upper()
    if tag == "BUY" and agents_hedge_on_pick(transcript):
        # Hedged agents → do not allow unqualified Buy confidence
        out["verdict"] = "MAYBE"
        w = dict(out.get("winner") or {})
        note = (
            " Agents hedged on safety/verification — confidence capped at Maybe, verify."
        )
        base = str(w.get("reason") or out.get("summary") or "").strip()
        if "confidence capped" not in base.lower():
            w["reason"] = (base + note).strip()
            out["winner"] = w
            out["summary"] = w["reason"]
        notes.append("confidence_capped_maybe")
        changed = True

    if changed and "hedged_language" not in notes:
        notes.append("hedged_language")
    return out, notes
