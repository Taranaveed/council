"""Phase 3 — watchlist + price-target alerts (in-app)."""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional

from app.db.users import DB_PATH, _connect


class WatchLimitError(ValueError):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(
            f"Watch limit reached ({limit}). Remove a watch before adding another."
        )


def init_watchlist_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                query_norm TEXT NOT NULL,
                location TEXT,
                currency TEXT,
                quantity INTEGER,
                max_unit_price REAL,
                max_landed REAL,
                active INTEGER NOT NULL DEFAULT 1,
                last_checked_at TEXT,
                last_best_price TEXT,
                last_best_link TEXT,
                last_alert TEXT,
                notes_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_watch_user_active "
            "ON watchlist_items(user_id, active)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watch_check_cache (
                cache_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                checked_at TEXT NOT NULL
            )
            """
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist_items)").fetchall()}
        if "last_notified_at" not in cols:
            conn.execute("ALTER TABLE watchlist_items ADD COLUMN last_notified_at TEXT")
        if "baseline_price" not in cols:
            conn.execute("ALTER TABLE watchlist_items ADD COLUMN baseline_price REAL")
        for name, sql_type in (
            ("tracked_url", "TEXT"),
            ("listing_title", "TEXT"),
            ("listing_vendor", "TEXT"),
            ("native_currency", "TEXT"),
            ("saved_price", "TEXT"),
            ("saved_price_source", "TEXT"),
            ("last_price_source", "TEXT"),
            ("last_alerted_price", "REAL"),
            ("last_alert_fingerprint", "TEXT"),
        ):
            if name not in cols:
                conn.execute(
                    f"ALTER TABLE watchlist_items ADD COLUMN {name} {sql_type}"
                )
        conn.commit()


def _row(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    if not row:
        return None
    d = dict(row)
    d["active"] = bool(d.get("active"))
    raw = d.pop("notes_json", None)
    notes = {}
    if raw:
        try:
            notes = json.loads(raw)
        except Exception:
            notes = {}
    d["notes"] = notes
    return d


def add_watch(
    *,
    user_id: int,
    item_name: str,
    location: str | None = None,
    currency: str | None = None,
    quantity: int | None = None,
    max_unit_price: float | None = None,
    max_landed: float | None = None,
    tracked_url: str | None = None,
    listing_title: str | None = None,
    listing_vendor: str | None = None,
    native_currency: str | None = None,
    saved_price: str | None = None,
    saved_price_source: str | None = None,
) -> dict[str, Any]:
    from app.db.briefs import normalize_query

    with _connect() as conn:
        max_watches = max(1, int(os.getenv("MAX_WATCHES_PER_USER") or "10"))
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM watchlist_items
            WHERE user_id = ? AND active = 1
            """,
            (user_id,),
        ).fetchone()
        if int(count_row["n"] if count_row else 0) >= max_watches:
            raise WatchLimitError(max_watches)
        cur = conn.execute(
            """
            INSERT INTO watchlist_items (
                user_id, item_name, query_norm, location, currency, quantity,
                max_unit_price, max_landed, tracked_url, listing_title,
                listing_vendor, native_currency, saved_price, saved_price_source,
                baseline_price, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                user_id,
                (item_name or "").strip()[:200],
                normalize_query(item_name),
                (location or "")[:120] or None,
                (currency or "")[:12] or None,
                quantity,
                max_unit_price,
                max_landed,
                (tracked_url or "")[:1000] or None,
                (listing_title or "")[:300] or None,
                (listing_vendor or "")[:120] or None,
                (native_currency or currency or "")[:12].upper() or None,
                (saved_price or "")[:80] or None,
                (saved_price_source or "snippet")[:30],
                _price_number(saved_price),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM watchlist_items WHERE id = ?",
            (int(cur.lastrowid),),
        ).fetchone()
        return _row(row) or {}


def list_watch(user_id: int, *, limit: int = 40) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 40), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM watchlist_items
            WHERE user_id = ? AND active = 1
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [_row(r) for r in rows if r]


def deactivate_watch(user_id: int, watch_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE watchlist_items SET active = 0 WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_watch_check(
    user_id: int,
    watch_id: int,
    *,
    best_price: str | None,
    best_link: str | None,
    alert: str | None,
    baseline_price: float | None = None,
    mark_notified: bool = False,
    price_source: str | None = None,
) -> Optional[dict[str, Any]]:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE watchlist_items
            SET last_checked_at = ?, last_best_price = ?, last_best_link = ?,
                last_alert = ?,
                last_notified_at = CASE WHEN ? THEN ? ELSE last_notified_at END,
                baseline_price = COALESCE(baseline_price, ?),
                last_price_source = COALESCE(?, last_price_source)
            WHERE id = ? AND user_id = ?
            """,
            (
                now,
                best_price,
                best_link,
                alert,
                1 if mark_notified else 0,
                now,
                baseline_price,
                price_source,
                watch_id,
                user_id,
            ),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM watchlist_items WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        ).fetchone()
        return _row(row)


def _price_number(raw: Any) -> float | None:
    import re

    if raw is None:
        return None
    match = re.search(r"([\d]+(?:[.,]\d+)?)", str(raw).replace(",", ""))
    if not match:
        return None
    try:
        value = float(match.group(1))
        return value if value > 0 else None
    except ValueError:
        return None


def get_watch(user_id: int, watch_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM watchlist_items WHERE id = ? AND user_id = ?",
            (watch_id, user_id),
        ).fetchone()
        return _row(row)


def mark_watch_alerted(
    user_id: int,
    watch_id: int,
    *,
    alerted_price: float | None,
    fingerprint: str,
) -> bool:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE watchlist_items
            SET last_notified_at = ?, last_alerted_price = ?,
                last_alert_fingerprint = ?
            WHERE id = ? AND user_id = ?
            """,
            (now, alerted_price, fingerprint[:200], watch_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def list_due_watches(*, stale_hours: float = 12.0, limit: int = 20) -> list[dict[str, Any]]:
    """Active watches that have never been checked or are older than stale_hours."""
    from datetime import datetime, timedelta, timezone

    limit = max(1, min(int(limit or 20), 50))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(0.25, float(stale_hours)))
    ).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM watchlist_items
            WHERE active = 1
              AND (
                last_checked_at IS NULL
                OR datetime(last_checked_at) <= datetime(?)
              )
            ORDER BY
              CASE WHEN last_checked_at IS NULL THEN 0 ELSE 1 END,
              datetime(last_checked_at) ASC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return [_row(r) for r in rows if r]


def list_active_watch_user_ids() -> list[int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM watchlist_items WHERE active = 1"
        ).fetchall()
        return [int(r["user_id"]) for r in rows]


def get_cached_watch_result(
    cache_key: str, *, ttl_hours: float = 6.0
) -> Optional[dict[str, Any]]:
    from datetime import datetime, timedelta, timezone

    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(0.0, float(ttl_hours)))
    ).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM watch_check_cache
            WHERE cache_key = ? AND datetime(checked_at) >= datetime(?)
            """,
            (cache_key, cutoff),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def put_cached_watch_result(cache_key: str, payload: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO watch_check_cache (cache_key, payload_json, checked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                checked_at = excluded.checked_at
            """,
            (cache_key[:1000], json.dumps(payload, default=str), now),
        )
        conn.commit()
