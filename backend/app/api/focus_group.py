import json
import re
from fastapi import APIRouter, Depends, HTTPException

from app.models.focus_group import (
    FocusGroupRequest,
    FocusGroupResponse,
    AgentTranscript,
    JudgeVerdict,
)
from app.core.llm_service import generate_non_streaming
from app.agents.focus_group_prompts import (
    skeptic_prompt,
    bargain_hunter_prompt,
    fan_prompt,
    judge_prompt,
)
from app.utils.price_classifier import classify_price
from app.core.auth import get_current_user

router = APIRouter(prefix="/focus-group", tags=["focus-group"])

MODEL = "openai/gpt-oss-120b"


def _product_block(req: FocusGroupRequest) -> str:
    return (
        f"Product: {req.product_name}\n"
        f"Price: {req.price} {req.currency}\n"
        f"Target Audience: {req.target_audience}\n"
        f"Description: {req.description}"
    )


def _build(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_json(text: str) -> dict:
    """Try three strategies: raw parse → strip markdown fences → regex extract {}."""
    candidates = [
        text,
        re.sub(r"```(?:json)?\s*|\s*```", "", text).strip(),
    ]
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        candidates.append(m.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return {}


@router.post("/run", response_model=FocusGroupResponse)
async def run_focus_group(req: FocusGroupRequest, _user: dict = Depends(get_current_user)):
    product = _product_block(req)

    currency = req.currency
    price_segment = classify_price(req.price, currency)

    # ── Step 1: Skeptic ──────────────────────────────────────────────────────
    try:
        skeptic = await generate_non_streaming(
            _build(skeptic_prompt(currency, price_segment), product),
            model=MODEL,
            max_tokens=220,
        )
    except Exception:
        raise HTTPException(status_code=502, detail="The agents could not finish this run. Try again shortly.")

    # ── Step 2: Bargain Hunter (sees product + Skeptic) ──────────────────────
    try:
        bargain = await generate_non_streaming(
            _build(
                bargain_hunter_prompt(currency, price_segment),
                f"{product}\n\nSkeptic's critique:\n{skeptic}",
            ),
            model=MODEL,
            max_tokens=220,
        )
    except Exception:
        raise HTTPException(status_code=502, detail="The agents could not finish this run. Try again shortly.")

    # ── Step 3: Target Fan (sees product + Skeptic + Bargain Hunter) ─────────
    try:
        fan = await generate_non_streaming(
            _build(
                fan_prompt(currency, price_segment),
                f"{product}\n\nSkeptic:\n{skeptic}\n\nBargain Hunter:\n{bargain}",
            ),
            model=MODEL,
            max_tokens=220,
        )
    except Exception:
        raise HTTPException(status_code=502, detail="The agents could not finish this run. Try again shortly.")

    # ── Step 4: Judge (full transcript → JSON) ───────────────────────────────
    transcript_text = (
        f"SKEPTIC:\n{skeptic}\n\n"
        f"BARGAIN HUNTER:\n{bargain}\n\n"
        f"TARGET FAN:\n{fan}"
    )
    try:
        judge_raw = await generate_non_streaming(
            _build(judge_prompt(currency, price_segment), transcript_text),
            model=MODEL,
            max_tokens=500,
            temperature=0.2,
            json_mode=True,
        )
    except Exception:
        raise HTTPException(status_code=502, detail="The agents could not finish this run. Try again shortly.")

    parsed = _extract_json(judge_raw)

    if not parsed or "launch_score" not in parsed:
        return FocusGroupResponse(
            transcript=AgentTranscript(
                skeptic=skeptic, bargain_hunter=bargain, target_fan=fan
            ),
            verdict=JudgeVerdict(
                summary="The Judge's output could not be parsed automatically.",
                biggest_red_flag="See raw verdict below.",
                biggest_selling_point="See raw verdict below.",
                launch_score=0,
            ),
            raw_verdict=judge_raw,
        )

    return FocusGroupResponse(
        transcript=AgentTranscript(skeptic=skeptic, bargain_hunter=bargain, target_fan=fan),
        verdict=JudgeVerdict(
            summary=parsed.get("summary", ""),
            biggest_red_flag=parsed.get("biggest_red_flag", ""),
            biggest_selling_point=parsed.get("biggest_selling_point", ""),
            launch_score=max(0, min(100, int(parsed.get("launch_score", 0)))),
        ),
    )
