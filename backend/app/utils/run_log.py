"""Persist a diffable JSON run log for each deal-finder invocation."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def _default_dir() -> Path:
    env = os.getenv("BUYER_COUNCIL_RUN_LOG_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "run_logs"


def write_run_log(payload: dict[str, Any], *, run_dir: Path | None = None) -> str:
    """
    Write one JSON file per run. Returns the absolute path.
    Fields expected: original_query, narrowed_query, result_urls, page_facts,
    calculator, agent_claims, verdict.
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
    return str(path.resolve())
