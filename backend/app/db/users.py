"""Simple SQLite user store for MVP auth."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "users.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def create_user(email: str, password_hash: str) -> dict:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email.lower().strip(), password_hash),
        )
        conn.commit()
        return get_user_by_id(cur.lastrowid)  # type: ignore[arg-type]


def get_user_by_email(email: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, role FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def set_user_role(user_id: int, role: str) -> Optional[dict]:
    with _connect() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()
    return get_user_by_id(user_id)
