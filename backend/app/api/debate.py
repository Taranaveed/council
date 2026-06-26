import json
import uuid
import re
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.debate import DebateContext, DebateRequest, DebateMessage, Speaker
from app.core.llm_service import stream_llm_response, generate_non_streaming

router = APIRouter(prefix="/debate", tags=["debate"])
active_debates: dict[str, DebateContext] = {}


@router.post("/start")
async def start_debate(request: DebateRequest):
    debate_id = str(uuid.uuid4())
    context = DebateContext(
        debate_id=debate_id,
        thesis=request.thesis,
        model=request.model,
        max_rounds=request.max_rounds,
    )
    active_debates[debate_id] = context
    return {"debate_id": debate_id, "status": "initialized"}


@router.get("/stream/{debate_id}")
async def stream_debate(debate_id: str):
    if debate_id not in active_debates:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    context = active_debates[debate_id]
    context.status = "running"

    async def debate_generator():
        for round_num in range(1, context.max_rounds + 1):
            context.current_round = round_num

            # PROPONENT TURN
            yield _sse_event({"type": "turn_start", "speaker": "proponent", "round": round_num})
            proponent_history = context.get_history_for_agent(Speaker.PROPONENT)
            proponent_content = ""

            async for chunk in stream_llm_response(proponent_history, model=context.model):
                data = json.loads(chunk.replace("data: ", "").strip())
                if data.get("type") == "delta":
                    token = data.get("content", "")
                    proponent_content += token
                    yield _sse_event({
                        "type": "token",
                        "speaker": "proponent",
                        "round": round_num,
                        "content": token,
                    })
                elif data.get("type") == "done":
                    clean = _strip_xml_tags(proponent_content, ["reasoning", "argument"])
                    msg = DebateMessage(
                        round=round_num,
                        speaker=Speaker.PROPONENT,
                        content=clean,
                        raw_reasoning=_extract_xml_content(proponent_content, "reasoning"),
                    )
                    context.add_message(msg)
                    yield _sse_event({
                        "type": "turn_end",
                        "speaker": "proponent",
                        "round": round_num,
                        "full_content": proponent_content,  # Show full response including reasoning
                    })

            # OPPONENT TURN
            yield _sse_event({"type": "turn_start", "speaker": "opponent", "round": round_num})
            opponent_history = context.get_history_for_agent(Speaker.OPPONENT)
            opponent_content = ""

            async for chunk in stream_llm_response(opponent_history, model=context.model):
                data = json.loads(chunk.replace("data: ", "").strip())
                if data.get("type") == "delta":
                    token = data.get("content", "")
                    opponent_content += token
                    yield _sse_event({
                        "type": "token",
                        "speaker": "opponent",
                        "round": round_num,
                        "content": token,
                    })
                elif data.get("type") == "done":
                    clean = _strip_xml_tags(opponent_content, ["analysis", "critique"])
                    msg = DebateMessage(
                        round=round_num,
                        speaker=Speaker.OPPONENT,
                        content=clean,
                        raw_reasoning=_extract_xml_content(opponent_content, "analysis"),
                    )
                    context.add_message(msg)
                    yield _sse_event({
                        "type": "turn_end",
                        "speaker": "opponent",
                        "round": round_num,
                        "full_content": opponent_content,  # Show full response including analysis
                    })

        # JUDGE PHASE
        yield _sse_event({"type": "turn_start", "speaker": "judge", "round": context.max_rounds + 1})
        judge_history = context.get_history_for_agent(Speaker.JUDGE)
        judge_response = await generate_non_streaming(judge_history, model=context.model)

        try:
            verdict = json.loads(_extract_json_block(judge_response))
        except json.JSONDecodeError:
            verdict = {"raw_verdict": judge_response}

        context.judge_verdict = verdict
        context.status = "completed"
        context.add_message(DebateMessage(
            round=context.max_rounds + 1,
            speaker=Speaker.JUDGE,
            content=json.dumps(verdict),
        ))

        yield _sse_event({"type": "judge_verdict", "speaker": "judge", "verdict": verdict})
        yield _sse_event({"type": "debate_complete"})

    return StreamingResponse(
        debate_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/result/{debate_id}")
async def get_debate_result(debate_id: str):
    if debate_id not in active_debates:
        raise HTTPException(status_code=404, detail="Debate not found")
    context = active_debates[debate_id]
    return {
        "debate_id": debate_id,
        "thesis": context.thesis,
        "status": context.status,
        "transcript": [m.model_dump() for m in context.transcript],
        "verdict": context.judge_verdict,
    }


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _strip_xml_tags(text: str, tags: list) -> str:
    for tag in tags:
        text = re.sub(rf"<\/?{tag}>.*?<\/?{tag}>", "", text, flags=re.DOTALL)
        text = re.sub(rf"<\/?{tag}>", "", text)
    return text.strip()


def _extract_xml_content(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_json_block(text: str) -> str:
    match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"({.*})", text, re.DOTALL)
    return match.group(1).strip() if match else text