"""Phase 3 — free-tier brief metering."""
from __future__ import annotations

import os
from typing import Any

from app.db.briefs import briefs_used_this_month


def monthly_limit() -> int:
    try:
        n = int(os.getenv("FREE_BRIEFS_PER_MONTH", "12"))
    except Exception:
        n = 12
    return max(1, min(n, 500))


def credit_status(user_id: int) -> dict[str, Any]:
    used = briefs_used_this_month(user_id)
    limit = monthly_limit()
    remaining = max(0, limit - used)
    return {
        "plan": "free",
        "used_this_month": used,
        "limit": limit,
        "remaining": remaining,
        "exhausted": remaining <= 0,
    }


def assert_can_run(user_id: int) -> dict[str, Any]:
    """Return status; caller raises HTTP 402/429 when exhausted."""
    return credit_status(user_id)
