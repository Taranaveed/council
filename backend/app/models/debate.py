from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime
from enum import Enum


class Speaker(str, Enum):
    PROPONENT = "proponent"
    OPPONENT = "opponent"
    JUDGE = "judge"


class DebateMessage(BaseModel):
    round: int
    speaker: Speaker
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    raw_reasoning: Optional[str] = None


class DebateContext(BaseModel):
    debate_id: str
    thesis: str
    model: str = "llama-3.3-70b-versatile"
    max_rounds: int = 3
    current_round: int = 0
    transcript: List[DebateMessage] = []
    status: Literal["pending", "running", "completed", "error"] = "pending"
    judge_verdict: Optional[dict] = None

    def add_message(self, msg: DebateMessage):
        self.transcript.append(msg)

    def get_history_for_agent(self, speaker: Speaker) -> List[dict]:
        history = []
        history.append({"role": "system", "content": self._get_system_prompt(speaker)})
        history.append({"role": "user", "content": f'The thesis: "{self.thesis}"'})
        for msg in self.transcript:
            role = "assistant" if msg.speaker == speaker else "user"
            history.append({
                "role": role,
                "content": f"[Round {msg.round}] {msg.speaker.value.upper()}: {msg.content}"
            })
        return history

    def _get_system_prompt(self, speaker: Speaker) -> str:
        from app.agents.prompts import (
            PROPONENT_SYSTEM_PROMPT,
            OPPONENT_SYSTEM_PROMPT,
            JUDGE_SYSTEM_PROMPT,
        )
        mapping = {
            Speaker.PROPONENT: PROPONENT_SYSTEM_PROMPT,
            Speaker.OPPONENT: OPPONENT_SYSTEM_PROMPT,
            Speaker.JUDGE: JUDGE_SYSTEM_PROMPT,
        }
        return mapping[speaker]


class DebateRequest(BaseModel):
    thesis: str
    max_rounds: int = Field(default=3, ge=1, le=10)
    model: str = "llama-3.3-70b-versatile"