from pydantic import BaseModel
from typing import Optional


class FocusGroupRequest(BaseModel):
    product_name: str
    price: str
    currency: str = "USD"
    target_audience: str
    description: str


class AgentTranscript(BaseModel):
    skeptic: str
    bargain_hunter: str
    target_fan: str


class JudgeVerdict(BaseModel):
    summary: str
    biggest_red_flag: str
    biggest_selling_point: str
    launch_score: int


class FocusGroupResponse(BaseModel):
    transcript: AgentTranscript
    verdict: JudgeVerdict
    raw_verdict: Optional[str] = None
