"""Phase 3 — watchlist + reorder reminders + alerts inbox + credits."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.alerts_service import check_one_watch, run_alerts_tick
from app.core.auth import get_current_user
from app.db import briefs as briefs_db
from app.db import credits as credits_db
from app.db import notifications as notif_db
from app.db import watchlist as watch_db

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class WatchCreate(BaseModel):
    item_name: str = Field(..., min_length=2, max_length=200)
    tracked_url: str = Field(..., min_length=8, max_length=1000)
    listing_title: Optional[str] = Field(default=None, max_length=300)
    listing_vendor: Optional[str] = Field(default=None, max_length=120)
    native_currency: str = Field(..., min_length=3, max_length=12)
    saved_price: str = Field(..., min_length=1, max_length=80)
    saved_price_source: str = Field(default="snippet", max_length=30)
    location: Optional[str] = None
    currency: Optional[str] = None
    quantity: Optional[int] = Field(default=None, ge=1, le=100000)
    max_unit_price: Optional[float] = Field(default=None, ge=0)
    max_landed: Optional[float] = Field(default=None, ge=0)


class OrderMark(BaseModel):
    days: int = Field(default=30, ge=7, le=180)


@router.get("/credits")
def get_credits(_user: dict = Depends(get_current_user)):
    return credits_db.credit_status(int(_user["id"]))


@router.get("/reminders")
def get_reminders(_user: dict = Depends(get_current_user)):
    return {"reminders": briefs_db.list_due_reminders(int(_user["id"]))}


@router.post("/reminders/{brief_id}/dismiss")
def dismiss_reminder(brief_id: int, _user: dict = Depends(get_current_user)):
    ok = briefs_db.dismiss_reminder(int(_user["id"]), brief_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"ok": True}


@router.get("/watchlist")
def get_watchlist(_user: dict = Depends(get_current_user)):
    return {"items": watch_db.list_watch(int(_user["id"]))}


@router.post("/watchlist")
def create_watch(body: WatchCreate, _user: dict = Depends(get_current_user)):
    row = watch_db.add_watch(
        user_id=int(_user["id"]),
        item_name=body.item_name,
        location=body.location,
        currency=body.currency,
        quantity=body.quantity,
        max_unit_price=body.max_unit_price,
        max_landed=body.max_landed,
        tracked_url=body.tracked_url,
        listing_title=body.listing_title,
        listing_vendor=body.listing_vendor,
        native_currency=body.native_currency,
        saved_price=body.saved_price,
        saved_price_source=body.saved_price_source,
    )
    return row


@router.delete("/watchlist/{watch_id}")
def remove_watch(watch_id: int, _user: dict = Depends(get_current_user)):
    ok = watch_db.deactivate_watch(int(_user["id"]), watch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Watch item not found")
    return {"ok": True}


@router.post("/watchlist/{watch_id}/check")
async def check_watch(watch_id: int, _user: dict = Depends(get_current_user)):
    """Live market re-check — fires inbox alert on target hit or price drop."""
    item = watch_db.get_watch(int(_user["id"]), watch_id)
    if not item:
        raise HTTPException(status_code=404, detail="Watch item not found")
    out = await check_one_watch(item, notify=True, force=True)
    row = out.get("watch") or item
    # Preserve response shape for existing UI; attach fire meta
    if isinstance(row, dict):
        row = {
            **row,
            "alert_fired": bool(out.get("fired")),
            "notification_id": (out.get("notification") or {}).get("id"),
        }
    return row


@router.get("/notifications")
def get_notifications(
    unread_only: bool = False,
    limit: int = 40,
    _user: dict = Depends(get_current_user),
):
    uid = int(_user["id"])
    return {
        "items": notif_db.list_notifications(
            uid, limit=limit, unread_only=unread_only
        ),
        "unread": notif_db.unread_count(uid),
    }


@router.post("/notifications/{notif_id}/read")
def read_notification(notif_id: int, _user: dict = Depends(get_current_user)):
    row = notif_db.mark_read(int(_user["id"]), notif_id)
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row


@router.post("/notifications/read-all")
def read_all_notifications(_user: dict = Depends(get_current_user)):
    n = notif_db.mark_all_read(int(_user["id"]))
    return {"ok": True, "marked": n}


@router.post("/alerts/run")
async def run_my_alerts(
    force: bool = False,
    _user: dict = Depends(get_current_user),
):
    """
    On-demand alerts tick for the signed-in user (dashboard open / refresh).
    Checks stale watches and materializes due reorder reminders into the inbox.
    """
    result = await run_alerts_tick(
        user_id=int(_user["id"]),
        watch_limit=6,
        force=force,
        stale_hours=0.0 if force else None,
    )
    uid = int(_user["id"])
    return {
        **result,
        "unread": notif_db.unread_count(uid),
        "notifications": notif_db.list_notifications(uid, limit=12),
        "reminders": briefs_db.list_due_reminders(uid),
    }
