"""Persist a diffable JSON run log for each deal-finder invocation."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.db.paths import (
    default_run_log_dir,
    run_log_keep,
    run_log_max_file_bytes,
    run_log_max_total_bytes,
)


def _default_dir() -> Path:
    return default_run_log_dir()


def _file_sizes(base: Path) -> list[tuple[Path, int]]:
    out: list[tuple[Path, int]] = []
    if not base.is_dir():
        return out
    for f in base.glob("*.json"):
        try:
            out.append((f, f.stat().st_size))
        except OSError:
            continue
    return out


def rotate_run_logs(base: Path, *, keep: int | None = None) -> int:
    """Enforce count + total-bytes caps. Returns number of files removed."""
    limit = keep if keep is not None else run_log_keep()
    max_total = run_log_max_total_bytes()
    if not base.is_dir():
        return 0
    files = sorted(base.glob("*.json"), key=lambda p: p.name)
    removed = 0

    # Count cap first (drop oldest).
    overflow = files[:-limit] if limit > 0 else list(files)
    for old in overflow:
        try:
            old.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue

    # Total-bytes cap: drop oldest until under budget.
    remaining = sorted(
        ((p, sz) for p, sz in _file_sizes(base)),
        key=lambda t: t[0].name,
    )
    total = sum(sz for _, sz in remaining)
    while remaining and total > max_total:
        old, sz = remaining.pop(0)
        try:
            old.unlink(missing_ok=True)
            removed += 1
            total -= sz
        except OSError:
            break
    return removed


def _truncate_payload(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Serialize payload; if over max_bytes, keep a stub that fits the limit."""
    raw = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    encoded = raw.encode("utf-8")
    if len(encoded) <= max_bytes:
        return payload
    stub = {
        "run_id": payload.get("run_id"),
        "ts": payload.get("ts"),
        "original_query": payload.get("original_query"),
        "narrowed_query": payload.get("narrowed_query"),
        "truncated": True,
        "original_bytes": len(encoded),
        "max_file_bytes": max_bytes,
        "verdict": payload.get("verdict"),
    }
    stub_raw = json.dumps(stub, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    if len(stub_raw) <= max_bytes:
        return stub
    # Extreme edge: drop verdict text too.
    tiny = {
        "run_id": payload.get("run_id"),
        "truncated": True,
        "original_bytes": len(encoded),
        "max_file_bytes": max_bytes,
    }
    return tiny


def write_run_log(payload: dict[str, Any], *, run_dir: Path | None = None) -> str:
    """
    Write one JSON file per run. Returns the absolute path.

    Optional / diagnostic only — default directory is ephemeral (temp), not
    the persistent data disk. Caps:
      - BUYER_COUNCIL_RUN_LOG_KEEP (default 40 files)
      - BUYER_COUNCIL_RUN_LOG_MAX_FILE_BYTES (default 500 KiB; oversized payloads truncated)
      - BUYER_COUNCIL_RUN_LOG_MAX_TOTAL_BYTES (default 8 MiB; oldest deleted)
    """
    base = run_dir or _default_dir()
    base.mkdir(parents=True, exist_ok=True)
    run_id = str(payload.get("run_id") or uuid.uuid4())
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = base / f"{stamp}_{run_id[:8]}.json"
    body = {
        "run_id": run_id,
        "ts": stamp,
        **payload,
    }
    max_file = run_log_max_file_bytes()
    body = _truncate_payload(body, max_file)
    text = json.dumps(body, indent=2, ensure_ascii=False, default=str)
    # Hard clamp encoded size if stub still somehow oversized.
    encoded = text.encode("utf-8")
    if len(encoded) > max_file:
        encoded = encoded[:max_file]
    path.write_bytes(encoded)
    rotate_run_logs(base)
    return str(path.resolve())
