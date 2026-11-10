"""Persist a diffable JSON run log for each deal-finder invocation."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.db.paths import default_run_log_dir, run_log_keep


def _default_dir() -> Path:
    return default_run_log_dir()


def rotate_run_logs(base: Path, *, keep: int | None = None) -> int:
    """Delete oldest ``*.json`` run logs beyond ``keep``. Returns removed count."""
    limit = keep if keep is not None else run_log_keep()
    if not base.is_dir():
        return 0
    files = sorted(base.glob("*.json"), key=lambda p: p.name)
    removed = 0
    for old in files[:-limit] if limit > 0 else files:
        try:
            old.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def write_run_log(payload: dict[str, Any], *, run_dir: Path | None = None) -> str:
    """
    Write one JSON file per run. Returns the absolute path.
    Fields expected: original_query, narrowed_query, result_urls, page_facts,
    calculator, agent_claims, verdict.

    Optional / diagnostic only — default directory is ephemeral (temp), not
    the persistent data disk. Override with BUYER_COUNCIL_RUN_LOG_DIR.
    Rotates to BUYER_COUNCIL_RUN_LOG_KEEP (default 40) files.
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
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    rotate_run_logs(base)
    return str(path.resolve())
