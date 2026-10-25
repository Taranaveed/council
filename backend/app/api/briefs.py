"""Buyer deal-brief workspace API (Phase 1–3)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.db import briefs as briefs_db
from app.models.briefs import (
    BriefDetail,
    BriefListResponse,
    BriefSummary,
    FakeCheapRequest,
)
from app.utils.supplier_table import (
    build_brief_export_text,
    build_negotiation_message,
    build_supplier_table,
)

router = APIRouter(prefix="/api/briefs", tags=["briefs"])


class OrderMarkRequest(BaseModel):
    days: int = Field(default=30, ge=7, le=180)


def _summary(row: dict, flags: dict[str, int] | None = None) -> BriefSummary:
    host = str(row.get("supplier_host") or "")
    return BriefSummary(
        id=int(row["id"]),
        run_id=row.get("run_id"),
        item_name=str(row.get("item_name") or ""),
        location=row.get("location"),
        currency=row.get("currency"),
        quantity=row.get("quantity"),
        buying_mode=row.get("buying_mode"),
        verdict_tag=row.get("verdict_tag"),
        winner_title=row.get("winner_title"),
        winner_vendor=row.get("winner_vendor"),
        winner_price=row.get("winner_price"),
        winner_link=row.get("winner_link"),
        supplier_host=row.get("supplier_host"),
        landed_mid=row.get("landed_mid"),
        summary=row.get("summary"),
        fake_cheap=bool(row.get("fake_cheap")),
        created_at=row.get("created_at"),
        supplier_fake_cheap_count=(flags or {}).get(host, 0) if host else 0,
    )


@router.get("", response_model=BriefListResponse)
def list_my_briefs(
    limit: int = 30,
    _user: dict = Depends(get_current_user),
):
    flags = briefs_db.supplier_flag_counts(int(_user["id"]))
    rows = briefs_db.list_briefs(int(_user["id"]), limit=limit)
    return BriefListResponse(
        briefs=[_summary(r, flags) for r in rows],
        supplier_flags=flags,
    )


@router.get("/shared/{token}")
def public_shared_brief(token: str):
    row = briefs_db.get_brief_by_share_token(token)
    if not row:
        raise HTTPException(status_code=404, detail="Shared brief not found")
    payload = row.get("payload") or {}
    return {
        "item_name": row.get("item_name"),
        "location": row.get("location"),
        "quantity": row.get("quantity"),
        "buying_mode": row.get("buying_mode"),
        "verdict_tag": row.get("verdict_tag"),
        "winner_title": row.get("winner_title"),
        "winner_vendor": row.get("winner_vendor"),
        "winner_price": row.get("winner_price"),
        "winner_link": row.get("winner_link"),
        "landed_mid": row.get("landed_mid"),
        "summary": row.get("summary"),
        "created_at": row.get("created_at"),
        "payload": {
            "verdict": payload.get("verdict"),
            "market_listings": (payload.get("market_listings") or [])[:12],
            "risk_score": payload.get("risk_score"),
            "query_meta": payload.get("query_meta"),
        },
        "read_only": True,
    }


@router.get("/{brief_id}", response_model=BriefDetail)
def get_my_brief(brief_id: int, _user: dict = Depends(get_current_user)):
    row = briefs_db.get_brief(int(_user["id"]), brief_id)
    if not row:
        raise HTTPException(status_code=404, detail="Brief not found")
    flags = briefs_db.supplier_flag_counts(int(_user["id"]))
    prior = briefs_db.find_prior_brief(
        int(_user["id"]),
        item_name=str(row.get("item_name") or ""),
        supplier_host=row.get("supplier_host"),
        exclude_id=int(row["id"]),
    )
    compare = briefs_db.compare_briefs(row, prior) if prior else None
    base = _summary(row, flags)
    return BriefDetail(**base.model_dump(), payload=row.get("payload") or {}, compare_to_prior=compare)


@router.post("/{brief_id}/fake-cheap", response_model=BriefDetail)
def set_fake_cheap(
    brief_id: int,
    body: FakeCheapRequest,
    _user: dict = Depends(get_current_user),
):
    row = briefs_db.mark_fake_cheap(int(_user["id"]), brief_id, fake=body.fake_cheap)
    if not row:
        raise HTTPException(status_code=404, detail="Brief not found")
    flags = briefs_db.supplier_flag_counts(int(_user["id"]))
    base = _summary(row, flags)
    return BriefDetail(**base.model_dump(), payload=row.get("payload") or {})


@router.post("/{brief_id}/share")
def share_brief(brief_id: int, _user: dict = Depends(get_current_user)):
    token = briefs_db.ensure_share_token(int(_user["id"]), brief_id)
    if not token:
        raise HTTPException(status_code=404, detail="Brief not found")
    frontend = (os.getenv("FRONTEND_ORIGIN") or "http://127.0.0.1:5173").rstrip("/")
    return {"token": token, "url": f"{frontend}/b/{token}"}



@router.get("/{brief_id}/export")
def export_brief(brief_id: int, _user: dict = Depends(get_current_user)):
    row = briefs_db.get_brief(int(_user["id"]), brief_id)
    if not row:
        raise HTTPException(status_code=404, detail="Brief not found")
    payload = row.get("payload") or {}
    verdict = payload.get("verdict") if isinstance(payload.get("verdict"), dict) else {}
    listings = payload.get("market_listings") if isinstance(payload.get("market_listings"), list) else []
    qm = payload.get("query_meta") if isinstance(payload.get("query_meta"), dict) else {}
    table = qm.get("supplier_table") if isinstance(qm.get("supplier_table"), list) else None
    if not table:
        table = build_supplier_table(
            listings,
            verdict=verdict,
            quantity=row.get("quantity"),
            is_bulk=str(row.get("buying_mode") or "") == "bulk",
        )
    neg = qm.get("negotiation_message")
    if not neg:
        neg = build_negotiation_message(
            item_name=str(row.get("item_name") or ""),
            quantity=row.get("quantity"),
            verdict=verdict,
            questions=[],
            location=row.get("location"),
        )
    token = briefs_db.ensure_share_token(int(_user["id"]), brief_id)
    frontend = (os.getenv("FRONTEND_ORIGIN") or "http://127.0.0.1:5173").rstrip("/")
    share_url = f"{frontend}/b/{token}" if token else None
    text = build_brief_export_text(
        item_name=str(row.get("item_name") or ""),
        location=row.get("location"),
        quantity=row.get("quantity"),
        buying_mode=row.get("buying_mode"),
        verdict=verdict,
        supplier_table=table or [],
        negotiation_message=neg,
        brief_id=int(row["id"]),
        share_url=share_url,
    )
    return {"text": text, "share_url": share_url, "supplier_table": table, "negotiation_message": neg}


@router.post("/{brief_id}/ordered", response_model=BriefDetail)
def mark_brief_ordered(
    brief_id: int,
    body: OrderMarkRequest,
    _user: dict = Depends(get_current_user),
):
    row = briefs_db.mark_ordered(int(_user["id"]), brief_id, days=body.days)
    if not row:
        raise HTTPException(status_code=404, detail="Brief not found")
    flags = briefs_db.supplier_flag_counts(int(_user["id"]))
    base = _summary(row, flags)
    return BriefDetail(**base.model_dump(), payload=row.get("payload") or {})
