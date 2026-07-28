"""Shared sequential multi-agent + judge debate runner."""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

from app.core.llm_service import DEFAULT_MODEL, generate_non_streaming

MODEL = DEFAULT_MODEL

_PLAIN_PROSE = (
    "\n\nOUTPUT STYLE: Write plain professional paragraphs only. "
    "Do not use markdown — no # headings, no * or ** emphasis, no backticks, "
    "and no dash/asterisk bullet lists. Separate points with short paragraphs."
)


def _build(system: str, user: str, *, plain_prose: bool = False) -> list[dict]:
    content = system + (_PLAIN_PROSE if plain_prose else "")
    return [{"role": "system", "content": content}, {"role": "user", "content": user}]


def _polish_agent_text(text: str) -> str:
    """Light cleanup so stored transcript is readable even before UI formatting."""
    t = str(text or "").strip()
    if not t:
        return t
    t = re.sub(r"```(?:\w+)?\s*|\s*```", "", t)
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"__(.+?)__", r"\1", t)
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^\s*[-*•]\s+", "• ", t, flags=re.M)
    return t.strip()


def extract_json(text: str) -> dict:
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


async def run_agent_debate(
    *,
    context: str,
    agents: list[tuple[str, str]],
    judge_prompt: str,
    agent_max_tokens: int = 280,
    judge_max_tokens: int = 600,
    fixed_replies: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any], str | None]:
    """
    Run agents sequentially; each later agent sees all prior turns.
    agents: list of (name, system_prompt)
    fixed_replies: skip LLM for named agents (used when live listings are empty).
    Returns (transcript_dict, verdict_dict, raw_verdict_if_parse_failed).
    """
    if not agents:
        raise HTTPException(status_code=500, detail="No agents configured for debate")

    fixed = fixed_replies or {}
    transcript: dict[str, str] = {}
    prior_blocks: list[str] = []

    for name, system_prompt in agents:
        if name in fixed:
            reply = fixed[name]
        else:
            user_content = context
            if prior_blocks:
                user_content = f"{context}\n\n" + "\n\n".join(prior_blocks)
            try:
                reply = await generate_non_streaming(
                    _build(system_prompt, user_content, plain_prose=True),
                    model=MODEL,
                    max_tokens=agent_max_tokens,
                )
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"{name} failed: {e}") from e

        transcript[name] = _polish_agent_text(reply)
        prior_blocks.append(f"{name}'s argument:\n{transcript[name]}")

    transcript_text = "\n\n".join(f"{name}:\n{text}" for name, text in transcript.items())

    try:
        judge_raw = await generate_non_streaming(
            _build(judge_prompt, f"Debate transcript:\n{transcript_text}"),
            model=MODEL,
            max_tokens=judge_max_tokens,
            temperature=0.2,
            json_mode=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Judge failed: {e}") from e

    verdict = extract_json(judge_raw)
    if not verdict:
        return transcript, {}, judge_raw
    return transcript, verdict, None


async def run_three_agent_debate(
    *,
    context: str,
    agent1_prompt: str,
    agent1_name: str,
    agent2_prompt: str,
    agent2_name: str,
    agent3_prompt: str,
    agent3_name: str,
    judge_prompt: str,
    agent_max_tokens: int = 280,
    judge_max_tokens: int = 600,
    fixed_replies: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any], str | None]:
    """Backward-compatible 3-agent wrapper."""
    return await run_agent_debate(
        context=context,
        agents=[
            (agent1_name, agent1_prompt),
            (agent2_name, agent2_prompt),
            (agent3_name, agent3_prompt),
        ],
        judge_prompt=judge_prompt,
        agent_max_tokens=agent_max_tokens,
        judge_max_tokens=judge_max_tokens,
        fixed_replies=fixed_replies,
    )
