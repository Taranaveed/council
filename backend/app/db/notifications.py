"""In-app notifications for deal alerts and reorder reminders."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.users import _connect


def init_notifications_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                href TEXT,
                meta_json TEXT,
                read_at TEXT,
                emailed_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                dedupe_key TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notif_user_created "
            "ON user_notifications(user_id, created_at DESC)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_notif_dedupe "
            "ON user_notifications(user_id, dedupe_key) "
            "WHERE dedupe_key IS NOT NULL"
        )
        conn.commit()


def _row(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    if not row:
        return None
    d = dict(row)
    raw = d.pop("meta_json", None)
    meta: dict[str, Any] = {}
    if raw:
        try:
            meta = json.loads(raw)
        except Exception:
            meta = {}
    d["meta"] = meta
    d["unread"] = not bool(d.get("read_at"))
    return d


def create_notification(
    *,
    user_id: int,
    kind: str,
    title: str,
    body: str,
    href: str | None = None,
    meta: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any] | None:
    """Insert notification. Returns None if dedupe_key already exists."""
    with _connect() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO user_notifications (
                    user_id, kind, title, body, href, meta_json, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    (kind or "alert")[:40],
                    (title or "")[:200],
                    (body or "")[:800],
                    (href or None),
                    json.dumps(meta or {}, ensure_ascii=False),
                    (dedupe_key or None),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return None
        row = conn.execute(
            "SELECT * FROM user_notifications WHERE id = ?",
            (int(cur.lastrowid),),
        ).fetchone()
        return _row(row)


def list_notifications(
    user_id: int, *, limit: int = 40, unread_only: bool = False
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 40), 100))
    with _connect() as conn:
        if unread_only:
            rows = conn.execute(
                """
                SELECT * FROM user_notifications
                WHERE user_id = ? AND read_at IS NULL
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM user_notifications
                WHERE user_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [_row(r) for r in rows if r]


def unread_count(user_id: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM user_notifications
            WHERE user_id = ? AND read_at IS NULL
            """,
            (user_id,),
        ).fetchone()
        return int(row["n"] if row else 0)


def mark_read(user_id: int, notif_id: int) -> Optional[dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE user_notifications
            SET read_at = COALESCE(read_at, ?)
            WHERE id = ? AND user_id = ?
            """,
            (now, notif_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM user_notifications WHERE id = ? AND user_id = ?",
            (notif_id, user_id),
        ).fetchone()
        return _row(row)


def mark_all_read(user_id: int) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE user_notifications
            SET read_at = ?
            WHERE user_id = ? AND read_at IS NULL
            """,
            (now, user_id),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def mark_emailed(notif_id: int) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE user_notifications SET emailed_at = ? WHERE id = ?",
            (now, notif_id),
        )
        conn.commit()
