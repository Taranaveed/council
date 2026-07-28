import asyncio
import os
import json
import re
from typing import AsyncGenerator

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

_client: AsyncGroq | None = None

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")


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
    return "rate_limit" in text or "429" in text or "tokens per day" in text


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
            stream = await _get_client().chat.completions.create(
                model=use_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
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
                    stream = await _get_client().chat.completions.create(
                        model=use_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
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
        kwargs = dict(
            model=use_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await _get_client().chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            last_err = e
            wait = _retry_after_seconds(e)
            # Short waits only (TPM); TPD often needs hours — skip long sleeps
            if wait is not None and wait <= 90:
                await asyncio.sleep(min(wait + 0.5, 90))
                try:
                    response = await _get_client().chat.completions.create(**kwargs)
                    return response.choices[0].message.content
                except Exception as e2:
                    last_err = e2
                    e = e2
            if _should_fallback(e) and i < len(models) - 1:
                print(f"[llm] {use_model} rate-limited; falling back to {models[i + 1]}")
                continue
            raise

    raise last_err or RuntimeError("LLM failed")
