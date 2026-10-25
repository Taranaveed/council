from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BriefSummary(BaseModel):
    id: int
    run_id: Optional[str] = None
    item_name: str
    location: Optional[str] = None
    currency: Optional[str] = None
    quantity: Optional[int] = None
    buying_mode: Optional[str] = None
    verdict_tag: Optional[str] = None
    winner_title: Optional[str] = None
    winner_vendor: Optional[str] = None
    winner_price: Optional[str] = None
    winner_link: Optional[str] = None
    supplier_host: Optional[str] = None
    landed_mid: Optional[str] = None
    summary: Optional[str] = None
    fake_cheap: bool = False
    created_at: Optional[str] = None
    supplier_fake_cheap_count: int = 0


class BriefDetail(BriefSummary):
    payload: dict[str, Any] = Field(default_factory=dict)
    compare_to_prior: Optional[dict[str, Any]] = None


class BriefListResponse(BaseModel):
    briefs: list[BriefSummary]
    supplier_flags: dict[str, int] = Field(default_factory=dict)


class FakeCheapRequest(BaseModel):
    fake_cheap: bool = True
