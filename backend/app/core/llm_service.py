import asyncio
import os
import json
import re
from typing import AsyncGenerator

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

_client: AsyncGroq | None = None

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")


def _is_gpt_oss(model: str | None) -> bool:
    return "gpt-oss" in str(model or "").lower()


def _extract_message_text(response) -> str:
    """Prefer visible content. Only use gpt-oss reasoning when it looks like the actual answer."""
    try:
        msg = response.choices[0].message
    except Exception:
        return ""
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(getattr(part, "text", None) or str(part or ""))
        content = "".join(parts)
    text = str(content or "").strip()
    if text:
        return text
    reasoning = str(
        getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None) or ""
    ).strip()
    if not reasoning:
        return ""
    # Chain-of-thought dumps are not user-facing answers.
    if re.match(r"(?i)^(the (user|task|request)|i need to|let me think|reasoning:)", reasoning):
        if "{" not in reasoning:
            return ""
    return reasoning


def _is_json_mode_fail(err: Exception) -> bool:
    text = str(err).lower()
    return (
        "json_validate_failed" in text
        or "failed to generate json" in text
        or "max completion tokens reached" in text
        or "failed_generation" in text
    )


def _completion_kwargs(model: str, extra: dict) -> dict:
    kwargs = dict(extra)
    if _is_gpt_oss(model):
        kwargs["reasoning_effort"] = extra.get("reasoning_effort", "low")
        # Reasoning tokens count against the cap. JSON mode needs a larger
        # ceiling or Groq returns json_validate_failed / truncated output.
        cap = int(kwargs.get("max_tokens") or 800)
        floor = 4000 if kwargs.get("response_format") else 2000
        kwargs["max_tokens"] = max(cap, floor)
    return kwargs


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to backend/.env to run debates."
            )
        _client = AsyncGroq(api_key=api_key)
    return _client


def _retry_after_seconds(err: Exception) -> float | None:
    """Parse Groq 'Please try again in XmYs' hint; None if not a short wait."""
    text = str(err)
    if "rate_limit" not in text.lower() and "429" not in text:
        return None
    m = re.search(r"try again in\s+(\d+)m\s*([\d.]+)s", text, re.I)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.search(r"try again in\s+([\d.]+)s", text, re.I)
    if m:
        return float(m.group(1))
    return 2.0


def _should_fallback(err: Exception) -> bool:
    text = str(err).lower()
    return (
        "rate_limit" in text
        or "429" in text
        or "tokens per day" in text
        or "model_not_found" in text
        or "does not exist" in text
        or _is_json_mode_fail(err)
    )


async def _create_completion(use_model: str, extra: dict):
    kwargs = _completion_kwargs(use_model, extra)
    try:
        return await _get_client().chat.completions.create(**kwargs)
    except Exception as e:
        if "reasoning_effort" in kwargs and "reasoning" in str(e).lower():
            kwargs.pop("reasoning_effort", None)
            return await _get_client().chat.completions.create(**kwargs)
        raise


async def stream_llm_response(
    messages: list,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
) -> AsyncGenerator[str, None]:
    primary = model or DEFAULT_MODEL
    models = [primary]
    if FALLBACK_MODEL and FALLBACK_MODEL != primary:
        models.append(FALLBACK_MODEL)

    last_err: Exception | None = None
    for i, use_model in enumerate(models):
        try:
            stream = await _create_completion(
                use_model,
                dict(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ),
            )
            if use_model != primary:
                yield _sse_event(
                    {
                        "type": "delta",
                        "content": f"[using fallback model {use_model}]\n\n",
                    }
                )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield _sse_event({"type": "delta", "content": delta})
                if chunk.choices[0].finish_reason:
                    yield _sse_event({"type": "done"})
            return
        except Exception as e:
            last_err = e
            wait = _retry_after_seconds(e)
            if wait is not None and wait <= 90 and i == 0:
                await asyncio.sleep(min(wait + 0.5, 90))
                try:
                    stream = await _create_completion(
                        use_model,
                        dict(
                            model=use_model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            stream=True,
                        ),
                    )
                    async for chunk in stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield _sse_event({"type": "delta", "content": delta})
                        if chunk.choices[0].finish_reason:
                            yield _sse_event({"type": "done"})
                    return
                except Exception as e2:
                    last_err = e2
            if not _should_fallback(e) or i == len(models) - 1:
                yield _sse_event({"type": "error", "content": str(e)})
                return
            continue

    yield _sse_event({"type": "error", "content": str(last_err or "LLM failed")})


async def generate_non_streaming(
    messages: list,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1200,
    json_mode: bool = False,
) -> str:
    primary = model or DEFAULT_MODEL
    models = [primary]
    if FALLBACK_MODEL and FALLBACK_MODEL != primary:
        models.append(FALLBACK_MODEL)

    last_err: Exception | None = None
    for i, use_model in enumerate(models):
        extra = dict(
            model=use_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            extra["response_format"] = {"type": "json_object"}

        try:
            response = await _create_completion(use_model, extra)
            text = _extract_message_text(response)
            if text:
                return text
            last_err = RuntimeError(f"{use_model} returned empty content")
            print(f"[llm] {use_model} empty reply; trying next model")
            if i < len(models) - 1:
                continue
            return ""
        except Exception as e:
            last_err = e
            if json_mode and _is_json_mode_fail(e):
                plain = dict(extra)
                plain.pop("response_format", None)
                plain["max_tokens"] = max(int(plain.get("max_tokens") or 1200), 4000)
                try:
                    response = await _create_completion(use_model, plain)
                    text = _extract_message_text(response)
                    if text:
                        print(f"[llm] {use_model} JSON mode truncated; recovered without json_object")
                        return text
                except Exception as e2:
                    last_err = e2
                    e = e2
            wait = _retry_after_seconds(e)
            if wait is not None and wait <= 90:
                await asyncio.sleep(min(wait + 0.5, 90))
                try:
                    response = await _create_completion(use_model, extra)
                    text = _extract_message_text(response)
                    if text:
                        return text
                except Exception as e2:
                    last_err = e2
                    e = e2
            if _should_fallback(e) and i < len(models) - 1:
                print(f"[llm] {use_model} failed; falling back to {models[i + 1]}: {e}")
                continue
            raise

    raise last_err or RuntimeError("LLM failed")


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
