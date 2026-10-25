"""Deal-alert + reorder-reminder automation (in-app + optional email)."""
from __future__ import annotations

import os
import re
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import briefs as briefs_db
from app.db import notifications as notif_db
from app.db import watchlist as watch_db
from app.db.users import get_user_by_id
from app.utils.notify_email import email_configured, send_alert_email

DROP_PCT = float(os.getenv("ALERT_DROP_PCT") or "0.05")  # 5%
ALERT_COOLDOWN_DAYS = float(os.getenv("ALERT_COOLDOWN_DAYS") or "3")
WATCH_CACHE_TTL_HOURS = float(os.getenv("WATCH_CACHE_TTL_HOURS") or "6")
FRONTEND = (os.getenv("FRONTEND_ORIGIN") or "http://127.0.0.1:5173").rstrip("/")
PUBLIC_API = (
    os.getenv("PUBLIC_API_ORIGIN") or "http://127.0.0.1:8000"
).rstrip("/")
EMAIL_DAILY_CAP = int(os.getenv("ALERT_EMAIL_DAILY_CAP") or "3")


def _send_notification_email(
    *,
    user_id: int,
    notification: dict[str, Any],
    subject: str,
    body: str,
) -> dict[str, Any]:
    if not email_configured():
        return {"ok": False, "skipped": True, "reason": "email_disabled"}
    if not notif_db.email_is_allowed(user_id):
        return {"ok": False, "skipped": True, "reason": "unsubscribed"}
    if notif_db.emailed_today_count(user_id) >= max(1, EMAIL_DAILY_CAP):
        return {"ok": False, "skipped": True, "reason": "daily_cap"}
    user = get_user_by_id(user_id) or {}
    token = notif_db.get_or_create_unsubscribe_token(user_id)
    unsubscribe_url = (
        f"{PUBLIC_API}/api/workspace/email/unsubscribe/{token}"
    )
    result = send_alert_email(
        to_email=str(user.get("email") or ""),
        subject=subject,
        body=f"{body}\n\nUnsubscribe: {unsubscribe_url}\n",
        unsubscribe_url=unsubscribe_url,
    )
    if result.get("ok") and notification.get("id"):
        notif_db.mark_emailed(int(notification["id"]))
    return result


def parse_price_num(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if float(raw) > 0 else None
    m = re.search(r"([\d]+(?:[.,]\d+)?)", str(raw).replace(",", ""))
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
        return n if n > 0 else None
    except Exception:
        return None


def evaluate_price_alert(
    *,
    best_n: float | None,
    best_price: str | None,
    best_link: str | None,
    vendor: str | None,
    max_unit_price: float | None,
    prior_best_n: float | None,
    baseline_n: float | None,
    drop_pct: float = DROP_PCT,
) -> dict[str, Any] | None:
    """
    Return alert payload when target hit or meaningful price drop vs prior/baseline.
    """
    if best_n is None or best_n <= 0:
        return None
    vendor_s = (vendor or "Seller").strip() or "Seller"
    price_s = best_price or str(best_n)

    if max_unit_price is not None and best_n <= float(max_unit_price):
        return {
            "kind": "deal_alert",
            "title": "Price target hit",
            "body": (
                f"{price_s} ≤ your max {max_unit_price} "
                f"({vendor_s}). Open the listing to verify before ordering."
            ),
            "href": best_link,
            "reason": "target",
        }

    ref = prior_best_n if prior_best_n and prior_best_n > 0 else baseline_n
    if ref and ref > 0 and best_n < ref * (1.0 - max(0.01, float(drop_pct))):
        pct = round((1.0 - best_n / ref) * 100)
        return {
            "kind": "price_drop",
            "title": "Price drop detected",
            "body": (
                f"{vendor_s} now {price_s} — about {pct}% below the last seen "
                f"({ref:g}). Better listing may be available."
            ),
            "href": best_link,
            "reason": "drop",
            "drop_pct": pct,
        }
    return None


def should_emit_alert(
    *,
    fingerprint: str,
    last_fingerprint: str | None,
    last_notified_at: str | None,
    cooldown_days: float = ALERT_COOLDOWN_DAYS,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Require a changed alert value and an elapsed cooldown."""
    if last_fingerprint and fingerprint == last_fingerprint:
        return False, "unchanged_since_last_alert"
    if last_notified_at:
        try:
            previous = datetime.fromisoformat(str(last_notified_at).replace("Z", ""))
            previous = previous.replace(tzinfo=None)
            current = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
            if current - previous < timedelta(days=max(0.0, float(cooldown_days))):
                return False, "cooldown"
        except (TypeError, ValueError):
            pass
    return True, "changed"


async def check_one_watch(
    item: dict[str, Any],
    *,
    notify: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Refresh the saved listing URL in its native currency."""
    from app.core.market_client import fetch_tracked_listing_price

    user_id = int(item["user_id"])
    watch_id = int(item["id"])
    query = str(item.get("item_name") or "")
    tracked_url = str(item.get("tracked_url") or "").strip()
    native_currency = str(
        item.get("native_currency") or item.get("currency") or "USD"
    ).upper()
    if not tracked_url:
        raise ValueError("Watch has no saved listing URL; remove it and watch a listing again.")

    cache_material = (
        f"{query.strip().lower()}|{tracked_url.strip().lower()}|{native_currency}"
    )
    cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
    refreshed = None if force else watch_db.get_cached_watch_result(
        cache_key, ttl_hours=WATCH_CACHE_TTL_HOURS
    )
    cache_hit = refreshed is not None
    if refreshed is None:
        refreshed = await fetch_tracked_listing_price(
            url=tracked_url,
            query=query,
            native_currency=native_currency,
        )
        watch_db.put_cached_watch_result(cache_key, refreshed)
    available = bool(refreshed.get("available"))
    vendor = str(item.get("listing_vendor") or "") or None
    best_link = tracked_url

    if not available:
        body = (
            f"The saved listing for {query} is unavailable. "
            "Council did not substitute another seller."
        )
        fingerprint = "listing_unavailable"
        allowed, suppress_reason = should_emit_alert(
            fingerprint=fingerprint,
            last_fingerprint=item.get("last_alert_fingerprint"),
            last_notified_at=item.get("last_notified_at"),
        )
        updated = watch_db.update_watch_check(
            user_id,
            watch_id,
            best_price=None,
            best_link=tracked_url,
            alert="Listing unavailable",
            price_source="unavailable",
        )
        notif = None
        if notify and allowed:
            notif = notif_db.create_notification(
                user_id=user_id,
                kind="listing_unavailable",
                title="Listing unavailable",
                body=body,
                href=tracked_url,
                meta={"watch_id": watch_id, "item_name": query},
                dedupe_key=f"watch:{watch_id}:unavailable:{datetime.now(timezone.utc).isoformat()}",
            )
            if notif:
                watch_db.mark_watch_alerted(
                    user_id,
                    watch_id,
                    alerted_price=None,
                    fingerprint=fingerprint,
                )
        return {
            "watch": updated or item,
            "fired": bool(notif),
            "notification": notif,
            "email": None,
            "best_price": None,
            "price_source": "unavailable",
            "cache_hit": cache_hit,
            "suppressed": not allowed,
            "suppress_reason": suppress_reason if not allowed else None,
        }

    page_price = refreshed.get("price")
    if page_price and refreshed.get("page_price_verified"):
        best_price = str(page_price)
        price_source = "page-verified price"
    else:
        best_price = str(item.get("saved_price") or "")
        price_source = "snippet price"
    best_n = parse_price_num(best_price)

    prior_n = parse_price_num(item.get("last_best_price"))
    baseline_n = item.get("baseline_price")
    try:
        baseline_f = float(baseline_n) if baseline_n is not None else None
    except (TypeError, ValueError):
        baseline_f = None

    alert_payload = evaluate_price_alert(
        best_n=best_n,
        best_price=best_price,
        best_link=best_link,
        vendor=vendor,
        max_unit_price=item.get("max_unit_price"),
        prior_best_n=prior_n,
        baseline_n=baseline_f,
    )

    alert_text = None
    alert_candidate = bool(alert_payload)
    fingerprint = (
        f"price:{native_currency}:{best_n:.8g}" if best_n is not None else "price:none"
    )
    allowed, suppress_reason = should_emit_alert(
        fingerprint=fingerprint,
        last_fingerprint=item.get("last_alert_fingerprint"),
        last_notified_at=item.get("last_notified_at"),
    )
    fired = bool(alert_candidate and allowed)
    if alert_payload:
        alert_text = f"{alert_payload['body']} [{price_source}; {native_currency}]"
        if not allowed:
            alert_text += f" Alert suppressed ({suppress_reason})."
    elif best_price:
        alert_text = (
            f"Checked saved listing. {price_source}: {best_price} "
            f"({native_currency})."
        )
    else:
        alert_text = "Saved listing is available, but no usable price was found."

    # Seed baseline on first successful priced check
    seed_baseline = best_n if (best_n is not None and baseline_f is None) else None

    updated = watch_db.update_watch_check(
        user_id,
        watch_id,
        best_price=best_price,
        best_link=best_link,
        alert=alert_text,
        baseline_price=seed_baseline if seed_baseline is not None else (
            best_n if fired and best_n is not None else None
        ),
        mark_notified=False,
        price_source=price_source,
    )

    notif = None
    email_result = None
    if fired and notify and alert_payload:
        dedupe = (
            f"watch:{watch_id}:{alert_payload['reason']}:"
            f"{fingerprint}:{datetime.now(timezone.utc).isoformat()}"
        )
        notif = notif_db.create_notification(
            user_id=user_id,
            kind=str(alert_payload["kind"]),
            title=str(alert_payload["title"]),
            body=f"{alert_payload['body']} [{price_source}; {native_currency}]",
            href=alert_payload.get("href"),
            meta={
                "watch_id": watch_id,
                "item_name": query,
                "best_price": best_price,
                "native_currency": native_currency,
                "price_source": price_source,
                "tracked_url": tracked_url,
                "reason": alert_payload.get("reason"),
            },
            dedupe_key=dedupe,
        )
        if notif:
            watch_db.mark_watch_alerted(
                user_id,
                watch_id,
                alerted_price=best_n,
                fingerprint=fingerprint,
            )
        if notif:
            link_line = f"\nListing: {best_link}" if best_link else ""
            desk = f"\nOpen Council: {FRONTEND}/buyer"
            email_result = _send_notification_email(
                user_id=user_id,
                notification=notif,
                subject=f"Council: {alert_payload['title']} — {query}",
                body=f"{alert_payload['body']}{link_line}{desk}\n",
            )

    return {
        "watch": updated or item,
        "fired": fired,
        "notification": notif,
        "email": email_result,
        "best_price": best_price,
        "cache_hit": cache_hit,
        "suppressed": bool(alert_candidate and not allowed),
        "suppress_reason": suppress_reason if alert_candidate and not allowed else None,
    }


async def process_reorder_reminders(*, limit: int = 40) -> dict[str, Any]:
    """Turn due 'I ordered this' rows into inbox (+ email) notifications once."""
    due = briefs_db.list_unnotified_due_reminders(limit=limit)
    created = 0
    emailed = 0
    for row in due:
        user_id = int(row["user_id"])
        brief_id = int(row["id"])
        name = str(row.get("item_name") or "your product")
        qty = row.get("quantity")
        vendor = row.get("winner_vendor")
        body = (
            f"Your stock of {name}"
            + (f" (qty {qty})" if qty is not None else "")
            + " may be running low — time to reorder?"
        )
        if vendor:
            body += f" Last winner: {vendor}."
        notif = notif_db.create_notification(
            user_id=user_id,
            kind="reorder_reminder",
            title="Reorder reminder",
            body=body,
            href=f"{FRONTEND}/buyer?brief={brief_id}",
            meta={
                "brief_id": brief_id,
                "item_name": name,
                "quantity": qty,
            },
            dedupe_key=f"reorder:{brief_id}",
        )
        briefs_db.mark_reminder_notified(user_id, brief_id)
        if notif:
            created += 1
            if email_configured():
                res = _send_notification_email(
                    user_id=user_id,
                    notification=notif,
                    subject=f"Council: Reorder reminder — {name}",
                    body=f"{body}\n\nOpen Council: {FRONTEND}/buyer?brief={brief_id}\n",
                )
                if res.get("ok"):
                    emailed += 1
    return {"reminders_due": len(due), "notifications_created": created, "emailed": emailed}


async def run_alerts_tick(
    *,
    stale_hours: float | None = None,
    watch_limit: int = 8,
    user_id: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Background / on-demand tick: check stale watches + fire reorder reminders.
    When user_id is set, only that user's watches are checked (dashboard refresh).
    """
    hours = stale_hours
    if hours is None:
        hours = float(os.getenv("ALERT_STALE_HOURS") or "12")
    if force:
        hours = 0.0

    if user_id is not None:
        items = [
            w
            for w in watch_db.list_watch(user_id, limit=40)
            if _is_stale(w, hours) or force
        ][:watch_limit]
    else:
        items = watch_db.list_due_watches(stale_hours=hours, limit=watch_limit)

    checked = 0
    fired = 0
    errors: list[str] = []
    for item in items:
        try:
            out = await check_one_watch(item, notify=True, force=force)
            checked += 1
            if out.get("fired"):
                fired += 1
        except Exception as exc:
            errors.append(f"watch:{item.get('id')}:{str(exc)[:80]}")

    rem = await process_reorder_reminders(limit=40)
    return {
        "watches_checked": checked,
        "alerts_fired": fired,
        "errors": errors[:5],
        **rem,
        "email_enabled": email_configured(),
    }


async def run_alerts_tick_locked(
    *,
    owner_id: str,
    lease_seconds: int = 600,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run one tick only when this process/request owns the DB lease."""
    lock_name = "alerts_scheduler"
    acquired = watch_db.acquire_automation_lock(
        lock_name,
        owner_id,
        lease_seconds=lease_seconds,
    )
    if not acquired:
        return {
            "skipped": True,
            "reason": "scheduler_lock_held",
            "watches_checked": 0,
            "alerts_fired": 0,
        }
    try:
        result = await run_alerts_tick(**kwargs)
        return {"skipped": False, **result}
    finally:
        watch_db.release_automation_lock(lock_name, owner_id)


def _is_stale(item: dict[str, Any], stale_hours: float) -> bool:
    raw = item.get("last_checked_at")
    if not raw:
        return True
    try:
        # SQLite stores naive ISO
        checked = datetime.fromisoformat(str(raw).replace("Z", ""))
        age_h = (datetime.now(timezone.utc).replace(tzinfo=None) - checked).total_seconds() / 3600.0
        return age_h >= float(stale_hours)
    except Exception:
        return True


async def alerts_background_loop() -> None:
    """Long-running poller started from app lifespan."""
    import asyncio

    enabled = (os.getenv("ALERTS_SCHEDULER") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if not enabled:
        return
    interval = float(os.getenv("ALERTS_POLL_SECONDS") or "900")  # 15 min
    interval = max(60.0, interval)
    owner_id = f"loop-{uuid.uuid4().hex}"
    # Small delay so startup DB init finishes
    await asyncio.sleep(8.0)
    while True:
        try:
            await run_alerts_tick_locked(
                owner_id=owner_id,
                lease_seconds=max(120, int(interval * 0.9)),
            )
        except Exception as exc:
            print(f"[alerts] tick error: {exc}")
        await asyncio.sleep(interval)
