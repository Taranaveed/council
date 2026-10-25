"""In-app notifications for deal alerts and reorder reminders."""
from __future__ import annotations

import json
import secrets
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
            """
            CREATE TABLE IF NOT EXISTS email_preferences (
                user_id INTEGER PRIMARY KEY,
                unsubscribe_token TEXT UNIQUE NOT NULL,
                unsubscribed_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_bounces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                event_type TEXT,
                provider_event_id TEXT,
                payload_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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


def get_or_create_unsubscribe_token(user_id: int) -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT unsubscribe_token FROM email_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return str(row["unsubscribe_token"])
        token = secrets.token_urlsafe(24)
        conn.execute(
            """
            INSERT INTO email_preferences (user_id, unsubscribe_token)
            VALUES (?, ?)
            """,
            (user_id, token),
        )
        conn.commit()
        return token


def email_is_allowed(user_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT unsubscribed_at FROM email_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row is None or not bool(row["unsubscribed_at"])


def unsubscribe_by_token(token: str) -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE email_preferences
            SET unsubscribed_at = COALESCE(unsubscribed_at, ?)
            WHERE unsubscribe_token = ?
            """,
            (now, (token or "").strip()),
        )
        conn.commit()
        return cur.rowcount > 0


def emailed_today_count(user_id: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM user_notifications
            WHERE user_id = ?
              AND emailed_at IS NOT NULL
              AND date(emailed_at) = date('now')
            """,
            (user_id,),
        ).fetchone()
        return int(row["n"] if row else 0)


def record_bounce(
    *,
    email: str,
    event_type: str | None,
    provider_event_id: str | None,
    payload: dict[str, Any] | None,
) -> None:
    """Provider-neutral bounce ingestion stub; stores event and suppresses email."""
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO email_bounces (
                email, event_type, provider_event_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                (email or "").lower().strip(),
                (event_type or "")[:80] or None,
                (provider_event_id or "")[:200] or None,
                json.dumps(payload or {}, default=str),
                now,
            ),
        )
        conn.execute(
            """
            UPDATE email_preferences
            SET unsubscribed_at = COALESCE(unsubscribed_at, ?)
            WHERE user_id IN (
                SELECT id FROM users WHERE lower(email) = lower(?)
            )
            """,
            (now, (email or "").strip()),
        )
        conn.commit()
