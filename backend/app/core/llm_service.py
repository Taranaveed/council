import os
import json
from typing import AsyncGenerator
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

_client: AsyncGroq | None = None


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


async def stream_llm_response(
    messages: list,
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 0.7,
    max_tokens: int = 800,
) -> AsyncGenerator[str, None]:
    try:
        stream = await _get_client().chat.completions.create(
            model=model,
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
    except Exception as e:
        yield _sse_event({"type": "error", "content": str(e)})


async def generate_non_streaming(
    messages: list,
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 0.7,
    max_tokens: int = 1200,
    json_mode: bool = False,
) -> str:
    kwargs = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = await _get_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"