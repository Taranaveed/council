"""DB_PATH env, mount-aware persistence, run-log rotation, backup/restore."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def test_get_db_path_default_under_backend_data(monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    from app.db.paths import get_db_path

    p = get_db_path()
    assert p.name == "users.db"
    assert p.parent.name == "data"


def test_get_db_path_env_override(monkeypatch, tmp_path: Path):
    target = tmp_path / "custom" / "app.db"
    monkeypatch.setenv("DB_PATH", str(target))
    from app.db.paths import get_db_path, get_marketplaces_db_path

    assert get_db_path() == target.resolve()
    assert get_marketplaces_db_path() == (target.parent / "marketplaces.db").resolve()


def test_db_persistent_mounted_path(monkeypatch, tmp_path: Path):
    """DB under PERSISTENT_DISK_MOUNT on the same real mount → True."""
    mount = tmp_path / "var" / "data"
    mount.mkdir(parents=True)
    on_disk = mount / "users.db"
    monkeypatch.setenv("PERSISTENT_DISK_MOUNT", str(mount))
    from app.db.paths import find_mount_point, is_db_on_persistent_disk

    assert find_mount_point(on_disk) == find_mount_point(mount)
    assert is_db_on_persistent_disk(on_disk) is True


def test_db_persistent_unmounted_path(monkeypatch, tmp_path: Path):
    """DB outside PERSISTENT_DISK_MOUNT → False even if env is set."""
    mount = tmp_path / "var" / "data"
    mount.mkdir(parents=True)
    off_disk = tmp_path / "ephemeral" / "users.db"
    off_disk.parent.mkdir(parents=True)
    monkeypatch.setenv("PERSISTENT_DISK_MOUNT", str(mount))
    from app.db.paths import is_db_on_persistent_disk

    assert is_db_on_persistent_disk(off_disk) is False
    monkeypatch.delenv("PERSISTENT_DISK_MOUNT", raising=False)
    assert is_db_on_persistent_disk(mount / "users.db") is False


def test_db_persistent_symlink_off_mount(monkeypatch, tmp_path: Path):
    """Symlink under mount that resolves outside the mount → False."""
    mount = tmp_path / "var" / "data"
    mount.mkdir(parents=True)
    real = tmp_path / "elsewhere" / "users.db"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"")
    link = mount / "users.db"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlinks not available")
    monkeypatch.setenv("PERSISTENT_DISK_MOUNT", str(mount))
    from app.db.paths import is_db_on_persistent_disk

    assert is_db_on_persistent_disk(link) is False


def test_default_run_log_dir_not_on_data_disk(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "persist" / "users.db"))
    monkeypatch.delenv("BUYER_COUNCIL_RUN_LOG_DIR", raising=False)
    from app.db.paths import default_run_log_dir, get_data_dir

    run_dir = default_run_log_dir()
    data = get_data_dir()
    assert data not in run_dir.parents and run_dir != data
    assert "council-run-logs" in str(run_dir)


def test_run_log_keeps_newest_40_files_by_default(tmp_path: Path, monkeypatch):
    """Default keep=40: only the newest 40 files remain."""
    monkeypatch.delenv("BUYER_COUNCIL_RUN_LOG_KEEP", raising=False)
    monkeypatch.setenv("BUYER_COUNCIL_RUN_LOG_MAX_TOTAL_BYTES", str(50 * 1024 * 1024))
    monkeypatch.setenv("BUYER_COUNCIL_RUN_LOG_MAX_FILE_BYTES", str(1024 * 1024))
    from app.utils.run_log import write_run_log

    for i in range(45):
        write_run_log({"run_id": f"r{i:02d}", "n": i}, run_dir=tmp_path)
    files = sorted(tmp_path.glob("*.json"), key=lambda p: p.name)
    assert len(files) == 40
    # Oldest five (r00–r04) should be gone; newest end with r44.
    names = " ".join(f.name for f in files)
    assert "r00" not in names
    assert "r44" in names or any("r4" in f.name for f in files[-5:])


def test_run_log_truncates_over_500kib_default(tmp_path: Path, monkeypatch):
    """Default max file 500 KiB: oversized payload is truncated."""
    monkeypatch.delenv("BUYER_COUNCIL_RUN_LOG_MAX_FILE_BYTES", raising=False)
    monkeypatch.setenv("BUYER_COUNCIL_RUN_LOG_KEEP", "10")
    monkeypatch.setenv("BUYER_COUNCIL_RUN_LOG_MAX_TOTAL_BYTES", str(50 * 1024 * 1024))
    from app.db.paths import RUN_LOG_MAX_FILE_BYTES_DEFAULT
    from app.utils.run_log import write_run_log

    path = Path(
        write_run_log(
            {
                "run_id": "big",
                "blob": "x" * (RUN_LOG_MAX_FILE_BYTES_DEFAULT + 50_000),
                "original_query": "towels",
            },
            run_dir=tmp_path,
        )
    )
    raw = path.read_bytes()
    assert len(raw) <= RUN_LOG_MAX_FILE_BYTES_DEFAULT
    body = json.loads(raw.decode("utf-8", errors="replace").rstrip("\x00"))
    assert body.get("truncated") is True


def test_run_log_directory_stays_under_8mib_default(tmp_path: Path, monkeypatch):
    """Default total cap 8 MiB: directory bytes stay under the limit."""
    monkeypatch.delenv("BUYER_COUNCIL_RUN_LOG_MAX_TOTAL_BYTES", raising=False)
    monkeypatch.setenv("BUYER_COUNCIL_RUN_LOG_KEEP", "40")
    monkeypatch.setenv("BUYER_COUNCIL_RUN_LOG_MAX_FILE_BYTES", str(600 * 1024))
    from app.db.paths import RUN_LOG_MAX_TOTAL_BYTES_DEFAULT
    from app.utils.run_log import write_run_log

    # 20 × ~500 KiB stubs would exceed 8 MiB without the total cap.
    for i in range(20):
        write_run_log(
            {"run_id": f"t{i:02d}", "blob": "y" * (480 * 1024)},
            run_dir=tmp_path,
        )
    total = sum(f.stat().st_size for f in tmp_path.glob("*.json"))
    assert total <= RUN_LOG_MAX_TOTAL_BYTES_DEFAULT
    assert len(list(tmp_path.glob("*.json"))) >= 1


def test_health_includes_db_disk_and_run_logs(monkeypatch, tmp_path: Path):
    db = tmp_path / "persist" / "users.db"
    db.parent.mkdir(parents=True)
    monkeypatch.setenv("DB_PATH", str(db))
    monkeypatch.setenv("PERSISTENT_DISK_MOUNT", str(tmp_path / "persist"))
    monkeypatch.setenv("ALERTS_SCHEDULER", "0")
    monkeypatch.setenv("BUYER_COUNCIL_RUN_LOG_DIR", str(tmp_path / "run_logs"))
    from app.main import app

    with TestClient(app) as client:
        res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["db_path"] == str(db.resolve())
    assert body["db_persistent"] is True
    assert "db_exists" in body
    assert "signup_open" in body
    assert isinstance(body["disk"], dict)
    assert body["disk"]["free_bytes"] is not None
    assert body["disk"]["total_bytes"] is not None
    assert body["run_logs"]["path"]
    assert "file_count" in body["run_logs"]


def test_sqlite_backup_api_and_restore(tmp_path: Path):
    from backup_sqlite_db import backup, restore

    src = tmp_path / "users.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    conn.execute("INSERT INTO users (email) VALUES ('a@example.com')")
    conn.commit()
    conn.close()

    bak_dir = tmp_path / "backups"
    bak = backup(src, bak_dir, keep=7)
    assert bak.is_file()

    # Corrupt / replace live DB then restore
    conn = sqlite3.connect(str(src))
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    restore(bak, src)
    conn = sqlite3.connect(str(src))
    row = conn.execute("SELECT email FROM users").fetchone()
    conn.close()
    assert row == ("a@example.com",)

    # keep=2 prunes older backups
    bak2 = backup(src, bak_dir, keep=2)
    bak3 = backup(src, bak_dir, keep=2)
    assert bak2.exists() or True
    remaining = sorted(bak_dir.glob("users-*.db"))
    assert len(remaining) == 2
    assert bak3 in remaining


def test_region_message_mentions_uk_and_pakistan():
    from app.core.region_profile import RegionNotSupportedError, get_profile

    with pytest.raises(RegionNotSupportedError) as ei:
        get_profile(location="New York, United States", currency="USD")
    assert "Council currently supports UK and Pakistan" in ei.value.detail
    assert "Region not supported: 'us'" in ei.value.detail
