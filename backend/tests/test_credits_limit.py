"""FREE_BRIEFS_PER_MONTH metering and user-safe limit message."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_monthly_limit_reads_env(monkeypatch):
    monkeypatch.setenv("FREE_BRIEFS_PER_MONTH", "3")
    from app.db.credits import monthly_limit

    assert monthly_limit() == 3


def test_free_briefs_limit_message_is_user_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("ALERTS_SCHEDULER", "0")
    monkeypatch.setenv("FREE_BRIEFS_PER_MONTH", "3")
    monkeypatch.delenv("SIGNUP_CODE", raising=False)

    from app.db import credits as credits_mod
    from app.main import app

    def _exhausted(_uid: int):
        return {
            "plan": "free",
            "used_this_month": 3,
            "limit": 3,
            "remaining": 0,
            "exhausted": True,
        }

    monkeypatch.setattr(credits_mod, "assert_can_run", _exhausted)

    email = f"hit_{uuid.uuid4().hex[:10]}@example.com"
    with TestClient(app) as client:
        reg = client.post(
            "/auth/register",
            json={"email": email, "password": "TestPass123!"},
        )
        assert reg.status_code == 200
        token = reg.json()["access_token"]
        res = client.post(
            "/api/modes/deal-finder",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "item_name": "phone case",
                "location": "London, United Kingdom",
                "currency": "GBP",
                "quantity": 10,
                "buying_mode": "bulk",
            },
        )
    assert res.status_code == 402
    detail = res.json()["detail"]
    assert isinstance(detail, str)
    assert detail == "You've used all free briefs for this month (3 of 3). Try again next month."
    assert "traceback" not in detail.lower()
    assert "/app/" not in detail
