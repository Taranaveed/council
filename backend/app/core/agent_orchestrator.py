"""Post-debate aggregation for buyer Deal Finder (risk score + scripts + checklists)."""
from __future__ import annotations

from typing import Any

from app.core.debate_runner import extract_json
from app.core.llm_service import generate_non_streaming

RISK_KEYWORDS = ("customs", "warranty", "shipping")


def compute_risk_score(transcript: dict[str, str]) -> dict[str, Any]:
    """
    Aggregate Risk Analyst warnings into a Risk Score.
    Each of customs / warranty / shipping found in Risk Analyst text increments +1.
    Score range: 0–3.
    """
    risk_text = (
        transcript.get("risk_analyst")
        or transcript.get("Risk Analyst")
        or ""
    )
    lowered = risk_text.lower()

    triggers: list[str] = []
    score = 0
    for keyword in RISK_KEYWORDS:
        if keyword in lowered:
            score += 1
            triggers.append(keyword)

    other_hits: list[str] = []
    for name, text in transcript.items():
        if name in ("risk_analyst", "Risk Analyst"):
            continue
        other_lower = (text or "").lower()
        for keyword in RISK_KEYWORDS:
            if keyword in other_lower and keyword not in other_hits:
                other_hits.append(keyword)

    level = "low" if score <= 1 else "medium" if score == 2 else "high"

    return {
        "score": score,
        "max_score": len(RISK_KEYWORDS),
        "level": level,
        "triggers": triggers,
        "echoed_by_others": other_hits,
        "source_agent": "risk_analyst",
    }


async def generate_negotiation_script(
    *,
    transcript: dict[str, str],
    verdict: dict[str, Any],
    item_name: str,
    buying_mode: str | None = None,
    quantity: int | None = None,
) -> list[str]:
    """Generate 3 seller questions when verdict is BUY. Falls back to templates."""
    if str(verdict.get("verdict", "")).upper() != "BUY":
        return []

    winner = verdict.get("winner") or {}
    debate = "\n\n".join(f"{k}:\n{v}" for k, v in transcript.items())
    is_bulk = (buying_mode or "").strip().lower() == "bulk" or (
        isinstance(quantity, int) and quantity >= 5
    )
    bulk_hint = ""
    if is_bulk:
        qty_bit = f" (~{quantity} units)" if quantity else ""
        bulk_hint = (
            f"Buyer is sourcing in bulk{qty_bit}. Prefer questions about MOQ, unit price, "
            "stock on hand, lead time, payment terms, and sample-before-full-order.\n"
        )
    prompt = (
        "You write short buyer negotiation scripts. Based on the deal debate, return JSON:\n"
        '{ "questions": ["q1", "q2", "q3"] }\n'
        "Exactly 3 practical questions the buyer should ask the seller before paying. "
        "Ground them in risks/gaps raised in the debate (warranty, condition, shipping, "
        "authenticity, paperwork, MOQ, etc.). Keep each question under 20 words.\n"
        f"{bulk_hint}"
        f"Item: {item_name}\n"
        f"Winner: {winner.get('vendor', '')} @ {winner.get('price', '')} — {winner.get('title', '')}\n"
        f"Debate:\n{debate[:3500]}"
    )

    try:
        raw = await generate_non_streaming(
            [
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=250,
            temperature=0.4,
            json_mode=True,
        )
        data = extract_json(raw)
        questions = data.get("questions") or []
        cleaned = [str(q).strip() for q in questions if str(q).strip()]
        if len(cleaned) >= 3:
            return cleaned[:3]
    except Exception as e:
        print(f"[agent_orchestrator] negotiation script failed: {e}")

    if is_bulk:
        return [
            "What is your MOQ, and can you fulfill my quantity at this unit price?",
            "How much stock is ready now, and what is the lead time for the rest?",
            "What payment terms do you offer, and can I buy a sample first?",
        ]

    return [
        "Do you provide a service warranty, and what does it cover?",
        "Can you show me the original receipt or proof of purchase?",
        "What is the shipping timeline, and who pays if customs fees apply?",
    ]


async def generate_buy_checklist(
    *,
    transcript: dict[str, str],
    verdict: dict[str, Any],
    item_name: str,
    marketplace: str | None = None,
    location: str | None = None,
) -> list[str]:
    """
    When verdict is PASS, generate a 'Buy Check-list' for users who still proceed
    against advice (especially on risky platforms).
    """
    if str(verdict.get("verdict", "")).upper() != "PASS":
        return []

    debate = "\n\n".join(f"{k}:\n{v}" for k, v in transcript.items())
    prompt = (
        "The Deal Judge returned PASS (do not buy). Some users will proceed anyway. "
        "Return JSON: { \"checklist\": [\"step1\", \"step2\", \"step3\"] }\n"
        "Write exactly 3 concrete harm-reduction steps starting from the debate risks. "
        "Tone: 'If you proceed against this advice, ensure you…'\n"
        "Examples of good steps: verify serial number on the brand site; only pay via a "
        "method that allows chargeback (not wire transfer); do not meet in a private residence.\n"
        "Keep each step under 25 words.\n"
        f"Item: {item_name}\n"
        f"Marketplace: {marketplace or 'unknown'}\n"
        f"Location: {location or 'unknown'}\n"
        f"Debate:\n{debate[:3500]}"
    )

    try:
        raw = await generate_non_streaming(
            [
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=280,
            temperature=0.35,
            json_mode=True,
        )
        data = extract_json(raw)
        items = data.get("checklist") or data.get("items") or []
        cleaned = [str(x).strip() for x in items if str(x).strip()]
        if len(cleaned) >= 3:
            return cleaned[:3]
    except Exception as e:
        print(f"[agent_orchestrator] buy checklist failed: {e}")

    return [
        "Verify the serial number / authenticity on the official brand website before paying.",
        "Only pay via a method that allows a chargeback (not wire transfer, gift cards, or cash apps).",
        "Do not meet in a private residence — use a safe public place and inspect the item first.",
    ]


class AgentOrchestrator:
    """Aggregates debate outputs for buyer-facing insights."""

    @staticmethod
    def risk_score_from_transcript(transcript: dict[str, str]) -> dict[str, Any]:
        return compute_risk_score(transcript)

    @staticmethod
    async def enrich_deal_verdict(
        *,
        transcript: dict[str, str],
        verdict: dict[str, Any],
        item_name: str,
        marketplace: str | None = None,
        location: str | None = None,
        buying_mode: str | None = None,
        quantity: int | None = None,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        risk = compute_risk_score(transcript)
        script = await generate_negotiation_script(
            transcript=transcript,
            verdict=verdict,
            item_name=item_name,
            buying_mode=buying_mode,
            quantity=quantity,
        )
        checklist = await generate_buy_checklist(
            transcript=transcript,
            verdict=verdict,
            item_name=item_name,
            marketplace=marketplace,
            location=location,
        )
        return risk, script, checklist