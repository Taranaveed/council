"""Alerts & Automation — price-drop rules, reorder notifications, inbox."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.core.alerts_service import (
    check_one_watch,
    evaluate_price_alert,
    parse_price_num,
    should_emit_alert,
)
from app.db import briefs as briefs_db
from app.db import notifications as notif_db
from app.db import watchlist as watch_db
from app.db.users import create_user, init_db
from app.db.briefs import init_briefs_db
from app.db.watchlist import init_watchlist_db
from app.db.notifications import init_notifications_db


def setup_module(_mod=None):
    init_db()
    init_briefs_db()
    init_watchlist_db()
    init_notifications_db()


def test_parse_price_num():
    assert parse_price_num("£11.50") == 11.5
    assert parse_price_num("$9") == 9.0
    assert parse_price_num("n/a") is None


def test_evaluate_target_hit():
    hit = evaluate_price_alert(
        best_n=8.0,
        best_price="£8",
        best_link="https://example.com/a",
        vendor="Alibaba",
        max_unit_price=10.0,
        prior_best_n=12.0,
        baseline_n=12.0,
    )
    assert hit is not None
    assert hit["reason"] == "target"
    assert hit["kind"] == "deal_alert"


def test_evaluate_price_drop_vs_prior():
    drop = evaluate_price_alert(
        best_n=9.0,
        best_price="$9",
        best_link="https://example.com/b",
        vendor="Factory",
        max_unit_price=None,
        prior_best_n=12.0,
        baseline_n=12.0,
        drop_pct=0.05,
    )
    assert drop is not None
    assert drop["reason"] == "drop"
    assert drop["kind"] == "price_drop"


def test_evaluate_no_alert_when_flat():
    # Above target and only ~4% below prior → no fire at 5% threshold
    none = evaluate_price_alert(
        best_n=11.5,
        best_price="£11.50",
        best_link=None,
        vendor="X",
        max_unit_price=10.0,
        prior_best_n=12.0,
        baseline_n=12.0,
        drop_pct=0.05,
    )
    assert none is None


def test_notification_inbox_and_dedupe(tmp_path=None):
    user = create_user(f"alerts_{uuid.uuid4().hex[:10]}@example.com", "hash")
    uid = int(user["id"])
    key = f"test-dedupe-{uid}-{uuid.uuid4().hex[:6]}"
    n1 = notif_db.create_notification(
        user_id=uid,
        kind="deal_alert",
        title="Price target hit",
        body="£8 ≤ max 10",
        dedupe_key=key,
    )
    assert n1 is not None
    n2 = notif_db.create_notification(
        user_id=uid,
        kind="deal_alert",
        title="dup",
        body="dup",
        dedupe_key=key,
    )
    assert n2 is None
    assert notif_db.unread_count(uid) >= 1
    notif_db.mark_read(uid, int(n1["id"]))
    assert notif_db.unread_count(uid) == 0


def test_watch_and_reorder_reminder_pipeline():
    user = create_user(f"reorder_{uuid.uuid4().hex[:10]}@example.com", "hash")
    uid = int(user["id"])
    watch = watch_db.add_watch(
        user_id=uid,
        item_name="phone case",
        location="London, United Kingdom",
        currency="GBP",
        quantity=100,
        max_unit_price=10.0,
    )
    assert watch.get("id")
    due = watch_db.list_due_watches(stale_hours=0.0, limit=50)
    assert any(int(w["id"]) == int(watch["id"]) for w in due)

    brief = briefs_db.save_brief(
        user_id=uid,
        run_id="test-alerts",
        item_name="phone case",
        location="London",
        currency="GBP",
        quantity=100,
        buying_mode="bulk",
        verdict={
            "verdict": "BUY",
            "winner": {
                "title": "Case",
                "vendor": "Alibaba",
                "price": "$9",
                "link": "https://www.alibaba.com/product-detail/x.html",
            },
        },
        market_listings=[],
    )
    briefs_db.mark_ordered(uid, int(brief["id"]), days=30)
    from datetime import datetime, timedelta, timezone
    from app.db.users import _connect

    past = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None).isoformat(
        timespec="seconds"
    )
    with _connect() as conn:
        conn.execute(
            "UPDATE deal_briefs SET remind_at = ?, remind_notified_at = NULL WHERE id = ?",
            (past, int(brief["id"])),
        )
        conn.commit()

    unnotified = briefs_db.list_unnotified_due_reminders(limit=50)
    assert any(int(r["id"]) == int(brief["id"]) for r in unnotified)

    import asyncio
    from app.core.alerts_service import process_reorder_reminders

    out = asyncio.run(process_reorder_reminders(limit=50))
    assert out["notifications_created"] >= 1
    inbox = notif_db.list_notifications(uid, limit=20)
    assert any(n.get("kind") == "reorder_reminder" for n in inbox)


def _tracked_watch(uid: int, **overrides):
    values = {
        "user_id": uid,
        "item_name": "phone case",
        "location": "London, UK",
        "currency": "GBP",
        "quantity": 100,
        "max_unit_price": 8.0,
        "tracked_url": "https://example.com/product/phone-case",
        "listing_title": "Phone Case",
        "listing_vendor": "Example",
        "native_currency": "USD",
        "saved_price": "$10.00",
        "saved_price_source": "snippet",
    }
    values.update(overrides)
    return watch_db.add_watch(**values)


def test_watch_uses_exact_url_page_price_in_native_currency():
    import asyncio

    user = create_user(f"tracked_{uuid.uuid4().hex[:10]}@example.com", "hash")
    watch = _tracked_watch(int(user["id"]))
    page = {
        "available": True,
        "url": watch["tracked_url"],
        "price": "$7.50",
        "currency": "USD",
        "price_source": "page",
        "page_price_verified": True,
    }
    with patch(
        "app.core.market_client.fetch_tracked_listing_price",
        new=AsyncMock(return_value=page),
    ) as fetch:
        out = asyncio.run(check_one_watch(watch, notify=False, force=True))
    fetch.assert_awaited_once_with(
        url=watch["tracked_url"],
        query="phone case",
        native_currency="USD",
    )
    assert out["watch"]["last_best_price"] == "$7.50"
    assert out["watch"]["last_price_source"] == "page-verified price"
    assert out["watch"]["last_best_link"] == watch["tracked_url"]


def test_watch_falls_back_to_labeled_snippet_price_when_page_has_no_price():
    import asyncio

    user = create_user(f"snippet_{uuid.uuid4().hex[:10]}@example.com", "hash")
    watch = _tracked_watch(int(user["id"]))
    with patch(
        "app.core.market_client.fetch_tracked_listing_price",
        new=AsyncMock(
            return_value={
                "available": True,
                "url": watch["tracked_url"],
                "price": None,
                "page_price_verified": False,
            }
        ),
    ):
        out = asyncio.run(check_one_watch(watch, notify=False, force=True))
    assert out["watch"]["last_best_price"] == "$10.00"
    assert out["watch"]["last_price_source"] == "snippet price"
    assert "snippet price" in out["watch"]["last_alert"]


def test_missing_saved_listing_notifies_unavailable_without_substitution():
    import asyncio

    user = create_user(f"missing_{uuid.uuid4().hex[:10]}@example.com", "hash")
    uid = int(user["id"])
    watch = _tracked_watch(uid)
    with patch(
        "app.core.market_client.fetch_tracked_listing_price",
        new=AsyncMock(
            return_value={"available": False, "reason": "listing_unavailable"}
        ),
    ):
        out = asyncio.run(check_one_watch(watch, notify=True, force=True))
    assert out["watch"]["last_alert"] == "Listing unavailable"
    assert out["watch"]["last_best_link"] == watch["tracked_url"]
    assert out["watch"]["last_best_price"] is None
    inbox = notif_db.list_notifications(uid, limit=20)
    assert any(
        n["kind"] == "listing_unavailable"
        and "did not substitute another seller" in n["body"]
        for n in inbox
    )


def test_alert_requires_changed_price_and_three_day_cooldown():
    now = datetime.now(timezone.utc)
    same, reason = should_emit_alert(
        fingerprint="price:USD:7.5",
        last_fingerprint="price:USD:7.5",
        last_notified_at=(now - timedelta(days=10)).isoformat(),
        cooldown_days=3,
        now=now,
    )
    assert same is False
    assert reason == "unchanged_since_last_alert"

    cooling, reason = should_emit_alert(
        fingerprint="price:USD:7",
        last_fingerprint="price:USD:7.5",
        last_notified_at=(now - timedelta(days=1)).isoformat(),
        cooldown_days=3,
        now=now,
    )
    assert cooling is False
    assert reason == "cooldown"

    changed, reason = should_emit_alert(
        fingerprint="price:USD:7",
        last_fingerprint="price:USD:7.5",
        last_notified_at=(now - timedelta(days=4)).isoformat(),
        cooldown_days=3,
        now=now,
    )
    assert changed is True
    assert reason == "changed"


def test_same_price_does_not_alert_twice():
    import asyncio

    user = create_user(f"cooldown_{uuid.uuid4().hex[:10]}@example.com", "hash")
    uid = int(user["id"])
    watch = _tracked_watch(uid)
    page = {
        "available": True,
        "url": watch["tracked_url"],
        "price": "$7.50",
        "currency": "USD",
        "price_source": "page",
        "page_price_verified": True,
    }
    with patch(
        "app.core.market_client.fetch_tracked_listing_price",
        new=AsyncMock(return_value=page),
    ):
        first = asyncio.run(check_one_watch(watch, notify=True, force=True))
        refreshed = watch_db.get_watch(uid, int(watch["id"]))
        second = asyncio.run(check_one_watch(refreshed, notify=True, force=True))
    assert first["notification"] is not None
    assert second["notification"] is None
    assert second["suppressed"] is True
    assert second["suppress_reason"] == "unchanged_since_last_alert"


def test_max_watches_per_user_has_clear_message(monkeypatch):
    monkeypatch.setenv("MAX_WATCHES_PER_USER", "2")
    user = create_user(f"limit_{uuid.uuid4().hex[:10]}@example.com", "hash")
    uid = int(user["id"])
    for i in range(2):
        _tracked_watch(
            uid,
            tracked_url=f"https://example.com/product/{i}",
        )
    try:
        _tracked_watch(uid, tracked_url="https://example.com/product/overflow")
        assert False, "expected WatchLimitError"
    except watch_db.WatchLimitError as exc:
        assert exc.limit == 2
        assert "Remove a watch before adding another" in str(exc)


def test_watch_cache_shared_across_users_for_same_query_and_url():
    import asyncio

    suffix = uuid.uuid4().hex[:10]
    u1 = create_user(f"cache1_{suffix}@example.com", "hash")
    u2 = create_user(f"cache2_{suffix}@example.com", "hash")
    url = f"https://example.com/product/shared-{suffix}"
    w1 = _tracked_watch(int(u1["id"]), tracked_url=url)
    w2 = _tracked_watch(int(u2["id"]), tracked_url=url)
    page = {
        "available": True,
        "url": url,
        "price": "$9.50",
        "currency": "USD",
        "price_source": "page",
        "page_price_verified": True,
    }
    fetch = AsyncMock(return_value=page)
    with patch(
        "app.core.market_client.fetch_tracked_listing_price",
        new=fetch,
    ):
        first = asyncio.run(check_one_watch(w1, notify=False, force=False))
        second = asyncio.run(check_one_watch(w2, notify=False, force=False))
    fetch.assert_awaited_once()
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
