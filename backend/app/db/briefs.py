"""Persisted buyer deal briefs (Phase 1 workspace)."""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from app.db.users import DB_PATH, _connect


def init_briefs_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deal_briefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                run_id TEXT,
                item_name TEXT NOT NULL,
                query_norm TEXT NOT NULL,
                location TEXT,
                currency TEXT,
                quantity INTEGER,
                buying_mode TEXT,
                verdict_tag TEXT,
                winner_title TEXT,
                winner_vendor TEXT,
                winner_price TEXT,
                winner_link TEXT,
                supplier_host TEXT,
                landed_mid TEXT,
                unit_price TEXT,
                summary TEXT,
                fake_cheap INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_briefs_user_created "
            "ON deal_briefs(user_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_briefs_user_query "
            "ON deal_briefs(user_id, query_norm)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_briefs_user_host "
            "ON deal_briefs(user_id, supplier_host)"
        )
        # Phase 2–3 columns (safe to re-run)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(deal_briefs)").fetchall()}
        if "share_token" not in cols:
            conn.execute("ALTER TABLE deal_briefs ADD COLUMN share_token TEXT")
        if "ordered_at" not in cols:
            conn.execute("ALTER TABLE deal_briefs ADD COLUMN ordered_at TEXT")
        if "remind_at" not in cols:
            conn.execute("ALTER TABLE deal_briefs ADD COLUMN remind_at TEXT")
        if "remind_notified_at" not in cols:
            conn.execute("ALTER TABLE deal_briefs ADD COLUMN remind_notified_at TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_briefs_share_token "
            "ON deal_briefs(share_token) WHERE share_token IS NOT NULL"
        )
        conn.commit()


def normalize_query(text: str) -> str:
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()[:160]


def host_from_link(link: str | None) -> str:
    try:
        host = urlparse(str(link or "")).hostname or ""
    except Exception:
        return ""
    return host.replace("www.", "").lower()[:120]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    payload = {}
    raw = d.pop("payload_json", None)
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
    d["payload"] = payload
    d["fake_cheap"] = bool(d.get("fake_cheap"))
    return d


def save_brief(
    *,
    user_id: int,
    run_id: str | None,
    item_name: str,
    location: str | None,
    currency: str | None,
    quantity: int | None,
    buying_mode: str | None,
    verdict: dict[str, Any],
    market_listings: list[dict[str, Any]],
    market_warning: str | None = None,
    risk_score: dict[str, Any] | None = None,
    query_meta: dict[str, Any] | None = None,
    transcript: dict[str, str] | None = None,
) -> dict[str, Any]:
    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    landed = verdict.get("landed_cost") if isinstance(verdict.get("landed_cost"), dict) else {}
    link = str(winner.get("link") or "")
    host = host_from_link(link)
    if not host and market_listings:
        host = host_from_link(str(market_listings[0].get("link") or ""))
    tag = str(verdict.get("verdict") or "").upper()
    payload = {
        "verdict": verdict,
        "market_listings": (market_listings or [])[:16],
        "market_warning": market_warning,
        "risk_score": risk_score,
        "query_meta": query_meta,
        "transcript": transcript or {},
    }
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO deal_briefs (
                user_id, run_id, item_name, query_norm, location, currency, quantity,
                buying_mode, verdict_tag, winner_title, winner_vendor, winner_price,
                winner_link, supplier_host, landed_mid, unit_price, summary,
                fake_cheap, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                user_id,
                run_id,
                (item_name or "").strip()[:200],
                normalize_query(item_name),
                (location or "")[:120] or None,
                (currency or "")[:12] or None,
                quantity,
                (buying_mode or "retail")[:20],
                tag[:20],
                str(winner.get("title") or "")[:200],
                str(winner.get("vendor") or "")[:120],
                str(winner.get("price") or "")[:80],
                link[:500],
                host or None,
                str(landed.get("estimated_total") or "")[:80] or None,
                str(winner.get("price") or landed.get("unit_price") or "")[:80] or None,
                str(verdict.get("summary") or "")[:500],
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
        return get_brief(user_id, int(cur.lastrowid))  # type: ignore[arg-type]


def get_brief(user_id: int, brief_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM deal_briefs WHERE id = ? AND user_id = ?",
            (brief_id, user_id),
        ).fetchone()
        return _row_to_dict(row) if row else None


def list_briefs(user_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 30), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, run_id, item_name, query_norm, location, currency,
                   quantity, buying_mode, verdict_tag, winner_title, winner_vendor,
                   winner_price, winner_link, supplier_host, landed_mid, unit_price,
                   summary, fake_cheap, created_at
            FROM deal_briefs
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["fake_cheap"] = bool(d.get("fake_cheap"))
            out.append(d)
        return out


def mark_fake_cheap(user_id: int, brief_id: int, *, fake: bool = True) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE deal_briefs SET fake_cheap = ? WHERE id = ? AND user_id = ?",
            (1 if fake else 0, brief_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_brief(user_id, brief_id)


def ensure_share_token(user_id: int, brief_id: int) -> Optional[str]:
    row = get_brief(user_id, brief_id)
    if not row:
        return None
    existing = row.get("share_token")
    if existing:
        return str(existing)
    token = secrets.token_urlsafe(18)
    with _connect() as conn:
        conn.execute(
            "UPDATE deal_briefs SET share_token = ? WHERE id = ? AND user_id = ?",
            (token, brief_id, user_id),
        )
        conn.commit()
    return token


def get_brief_by_share_token(token: str) -> Optional[dict[str, Any]]:
    t = (token or "").strip()
    if not t or len(t) < 8:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM deal_briefs WHERE share_token = ?",
            (t,),
        ).fetchone()
        return _row_to_dict(row) if row else None


def mark_ordered(user_id: int, brief_id: int, *, days: int = 30) -> Optional[dict[str, Any]]:
    """Phase 3 — user says they ordered; schedule a reorder nudge."""
    now = datetime.now(timezone.utc)
    remind = now + timedelta(days=max(1, min(int(days or 30), 180)))
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE deal_briefs
            SET ordered_at = ?, remind_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                now.replace(tzinfo=None).isoformat(timespec="seconds"),
                remind.replace(tzinfo=None).isoformat(timespec="seconds"),
                brief_id,
                user_id,
            ),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_brief(user_id, brief_id)


def list_due_reminders(user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    limit = max(1, min(int(limit or 20), 50))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, item_name, quantity, verdict_tag, winner_vendor, remind_at,
                   ordered_at, remind_notified_at, location, currency, buying_mode
            FROM deal_briefs
            WHERE user_id = ?
              AND remind_at IS NOT NULL
              AND remind_at <= ?
            ORDER BY remind_at ASC
            LIMIT ?
            """,
            (user_id, now, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_unnotified_due_reminders(*, limit: int = 40) -> list[dict[str, Any]]:
    """Reorder nudges that are due and have not yet produced a notification."""
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    limit = max(1, min(int(limit or 40), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, item_name, quantity, verdict_tag, winner_vendor,
                   remind_at, ordered_at, location, currency, buying_mode
            FROM deal_briefs
            WHERE remind_at IS NOT NULL
              AND remind_at <= ?
              AND remind_notified_at IS NULL
            ORDER BY remind_at ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_reminder_notified(user_id: int, brief_id: int) -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE deal_briefs
            SET remind_notified_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (now, brief_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def dismiss_reminder(user_id: int, brief_id: int) -> bool:
    """Clear remind_at so the nudge stops showing; keep ordered_at history."""
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE deal_briefs
            SET remind_at = NULL, remind_notified_at = COALESCE(remind_notified_at, ?)
            WHERE id = ? AND user_id = ?
            """,
            (
                datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
                brief_id,
                user_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def briefs_used_this_month(user_id: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM deal_briefs
            WHERE user_id = ?
              AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
            """,
            (user_id,),
        ).fetchone()
        return int(row["n"] if row else 0)


def supplier_flag_counts(user_id: int) -> dict[str, int]:
    """How many times this user marked fake-cheap per supplier host."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT supplier_host, COUNT(*) AS n
            FROM deal_briefs
            WHERE user_id = ? AND fake_cheap = 1 AND supplier_host IS NOT NULL AND supplier_host != ''
            GROUP BY supplier_host
            """,
            (user_id,),
        ).fetchall()
        return {str(r["supplier_host"]): int(r["n"]) for r in rows}


def find_prior_brief(
    user_id: int,
    *,
    item_name: str,
    supplier_host: str | None = None,
    exclude_id: int | None = None,
) -> Optional[dict[str, Any]]:
    """Most recent prior brief for same normalized query (or same supplier host)."""
    qn = normalize_query(item_name)
    with _connect() as conn:
        if qn:
            row = conn.execute(
                """
                SELECT * FROM deal_briefs
                WHERE user_id = ? AND query_norm = ?
                  AND (? IS NULL OR id != ?)
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """,
                (user_id, qn, exclude_id, exclude_id),
            ).fetchone()
            if row:
                return _row_to_dict(row)
        host = (supplier_host or "").strip().lower()
        if host:
            row = conn.execute(
                """
                SELECT * FROM deal_briefs
                WHERE user_id = ? AND supplier_host = ?
                  AND (? IS NULL OR id != ?)
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 1
                """,
                (user_id, host, exclude_id, exclude_id),
            ).fetchone()
            if row:
                return _row_to_dict(row)
    return None


def compare_briefs(current: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """Lightweight delta for UI — prices as strings; flip if verdict changed."""
    cur_tag = str(current.get("verdict_tag") or "").upper()
    prior_tag = str(prior.get("verdict_tag") or "").upper()
    return {
        "prior_brief_id": prior.get("id"),
        "prior_created_at": prior.get("created_at"),
        "prior_verdict": prior_tag,
        "prior_winner_vendor": prior.get("winner_vendor"),
        "prior_winner_price": prior.get("winner_price"),
        "prior_landed_mid": prior.get("landed_mid"),
        "prior_item_name": prior.get("item_name"),
        "current_verdict": cur_tag,
        "current_winner_price": current.get("winner_price"),
        "current_landed_mid": current.get("landed_mid"),
        "verdict_flipped": cur_tag != prior_tag and bool(cur_tag and prior_tag),
        "same_supplier": bool(
            current.get("supplier_host")
            and current.get("supplier_host") == prior.get("supplier_host")
        ),
        "match_basis": (
            "same_query"
            if current.get("query_norm") and current.get("query_norm") == prior.get("query_norm")
            else "same_supplier"
        ),
    }


# Ensure table exists when module is imported in tests / late init
def ensure_ready() -> None:
    if not DB_PATH.parent.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_briefs_db()
