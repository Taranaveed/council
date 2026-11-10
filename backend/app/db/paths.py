"""Resolve SQLite and related data paths (DB_PATH env)."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# Default mount used on Render when a persistent disk is attached (see render.yaml).
DEFAULT_PERSISTENT_MOUNT = "/var/data"

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_USERS_DB = _BACKEND_ROOT / "data" / "users.db"

# Cap diagnostic run logs so they cannot fill the ephemeral volume.
RUN_LOG_KEEP_DEFAULT = 40
RUN_LOG_MAX_FILE_BYTES_DEFAULT = 500 * 1024  # 500 KiB per file
RUN_LOG_MAX_TOTAL_BYTES_DEFAULT = 8 * 1024 * 1024  # 8 MiB across the dir


def get_db_path() -> Path:
    """Primary SQLite file (users, briefs, watchlist, notifications, credits).

    DB_PATH env overrides the default ``backend/data/users.db``.
    """
    raw = (os.getenv("DB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_USERS_DB.resolve()


def get_data_dir() -> Path:
    """Directory that holds users.db and sibling SQLite files."""
    return get_db_path().parent


def get_marketplaces_db_path() -> Path:
    """Marketplace seed DB — same directory as users.db (re-seedable)."""
    return get_data_dir() / "marketplaces.db"


def get_persistent_disk_mount() -> Path | None:
    """Configured disk mount path, or None if unset/empty."""
    raw = (os.getenv("PERSISTENT_DISK_MOUNT") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def find_mount_point(path: Path) -> Path:
    """Return the filesystem mount point that contains ``path``.

    Walks parents until ``st_dev`` changes (POSIX/Windows). For a path that
    does not exist yet, starts from the nearest existing ancestor.
    """
    cur = path.expanduser()
    try:
        cur = cur.resolve()
    except OSError:
        cur = cur.absolute()
    while not cur.exists() and cur != cur.parent:
        cur = cur.parent
    if cur.is_file():
        cur = cur.parent
    try:
        dev = cur.stat().st_dev
    except OSError:
        return cur
    while cur != cur.parent:
        parent = cur.parent
        try:
            if parent.stat().st_dev != dev:
                return cur
        except OSError:
            return cur
        cur = parent
    return cur


def is_db_on_persistent_disk(db_path: Path | None = None) -> bool:
    """True when DB_PATH lives under PERSISTENT_DISK_MOUNT on that mount's device.

    Uses the *real* mount point of DB_PATH (via st_dev), not a string-prefix
    check alone — so a symlink off the disk cannot report as persistent.
    """
    mount_cfg = get_persistent_disk_mount()
    if mount_cfg is None:
        return False
    path = (db_path or get_db_path()).resolve()
    try:
        path.relative_to(mount_cfg)
    except ValueError:
        return False
    # Both the DB and the configured mount must sit on the same real mount.
    return find_mount_point(path) == find_mount_point(mount_cfg)


def default_run_log_dir() -> Path:
    """Deal-finder JSON run logs — ephemeral by default (not on the data disk).

    Override with BUYER_COUNCIL_RUN_LOG_DIR. Default is under the system temp
    dir so Render's /var/data disk is not filled with diagnostics.
    """
    env = (os.getenv("BUYER_COUNCIL_RUN_LOG_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "council-run-logs").resolve()


def run_log_keep() -> int:
    raw = (os.getenv("BUYER_COUNCIL_RUN_LOG_KEEP") or "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return RUN_LOG_KEEP_DEFAULT


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return default


def run_log_max_file_bytes() -> int:
    return _env_int("BUYER_COUNCIL_RUN_LOG_MAX_FILE_BYTES", RUN_LOG_MAX_FILE_BYTES_DEFAULT)


def run_log_max_total_bytes() -> int:
    return _env_int("BUYER_COUNCIL_RUN_LOG_MAX_TOTAL_BYTES", RUN_LOG_MAX_TOTAL_BYTES_DEFAULT)


def disk_usage_report(path: Path | None = None) -> dict[str, int | str | None]:
    """Filesystem capacity for the volume that holds ``path`` (default: DB)."""
    target = path or get_db_path()
    probe = target if target.exists() else target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return {
            "path": str(target),
            "mount_point": None,
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
        }
    mount = find_mount_point(probe)
    return {
        "path": str(target),
        "mount_point": str(mount),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": int(usage.free),
    }


def run_log_dir_usage() -> dict[str, int | str]:
    """Bytes used by files currently in the run-log directory (after rotation)."""
    base = default_run_log_dir()
    total = 0
    count = 0
    if base.is_dir():
        for f in base.glob("*.json"):
            try:
                total += f.stat().st_size
                count += 1
            except OSError:
                continue
    return {
        "path": str(base),
        "file_count": count,
        "bytes": total,
        "keep": run_log_keep(),
        "max_file_bytes": run_log_max_file_bytes(),
        "max_total_bytes": run_log_max_total_bytes(),
    }
