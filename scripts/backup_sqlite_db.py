#!/usr/bin/env python3
"""Online-backup the Council SQLite DB via sqlite3 backup API; keep last 7.

Uses Connection.backup() (consistent snapshot; safe with WAL) instead of
raw file copy.

Usage:
  python scripts/backup_sqlite_db.py
  python scripts/backup_sqlite_db.py --db /var/data/users.db --dir /var/data/backups
  python scripts/backup_sqlite_db.py --restore /var/data/backups/users-….db

Env:
  DB_PATH           Source DB (default: backend/data/users.db)
  DB_BACKUP_DIR     Backup directory (default: <db_parent>/backups)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

KEEP = 7


def _default_db() -> Path:
    raw = (os.getenv("DB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "backend" / "data" / "users.db").resolve()


def _default_backup_dir(db_path: Path) -> Path:
    env_dir = (os.getenv("DB_BACKUP_DIR") or "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return (db_path.parent / "backups").resolve()


def sqlite_backup(source: Path, dest: Path) -> None:
    """Copy ``source`` → ``dest`` using the SQLite backup API."""
    if not source.is_file():
        raise FileNotFoundError(f"DB not found: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def prune_backups(backup_dir: Path, keep: int = KEEP) -> None:
    existing = sorted(backup_dir.glob("users-*.db"), key=lambda p: p.name)
    for old in existing[:-keep] if keep > 0 else existing:
        old.unlink(missing_ok=True)


def backup(db_path: Path, backup_dir: Path, keep: int = KEEP) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = backup_dir / f"users-{stamp}.db"
    # Extremely unlikely collision within the same microsecond:
    n = 0
    while dest.exists():
        n += 1
        dest = backup_dir / f"users-{stamp}-{n}.db"
    sqlite_backup(db_path, dest)
    prune_backups(backup_dir, keep=max(1, keep))
    return dest


def restore(backup_file: Path, db_path: Path) -> Path:
    """Restore a backup file onto ``db_path`` via the SQLite backup API."""
    if not backup_file.is_file():
        raise FileNotFoundError(f"Backup not found: {backup_file}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Remove WAL/SHM so restore is the sole truth
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    sqlite_backup(backup_file, db_path)
    return db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backup/restore Council SQLite DB via sqlite3 backup API (keep last 7)."
    )
    parser.add_argument("--db", type=Path, default=None, help="Live users.db path")
    parser.add_argument("--dir", type=Path, default=None, help="Backup directory")
    parser.add_argument("--keep", type=int, default=KEEP)
    parser.add_argument(
        "--restore",
        type=Path,
        default=None,
        help="Restore this backup file onto --db (or DB_PATH)",
    )
    args = parser.parse_args(argv)
    db_path = (args.db or _default_db()).resolve()
    try:
        if args.restore is not None:
            out = restore(args.restore.expanduser().resolve(), db_path)
            print(f"restore_ok path={out}")
            return 0
        backup_dir = (
            args.dir.expanduser().resolve()
            if args.dir is not None
            else _default_backup_dir(db_path)
        )
        dest = backup(db_path, backup_dir, keep=max(1, int(args.keep)))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"backup_ok path={dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
