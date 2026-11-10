"""signup_open on /health; loud warning when open in production."""
from __future__ import annotations

import logging

from fastapi.testclient import TestClient


def test_health_signup_open_true_when_unset(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("ALERTS_SCHEDULER", "0")
    monkeypatch.delenv("SIGNUP_CODE", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    from app.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["signup_open"] is True


def test_health_signup_open_false_when_code_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("ALERTS_SCHEDULER", "0")
    monkeypatch.setenv("SIGNUP_CODE", "invite-testers-only")
    from app.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["signup_open"] is False
    assert "SIGNUP_CODE" not in str(body)
    assert "invite-testers-only" not in str(body)


def test_signup_open_warns_in_production(monkeypatch, caplog):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("SIGNUP_CODE", raising=False)
    from app.core import prod_env

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        prod_env.warn_if_signup_open_in_production()
    assert any("registration is OPEN" in r.message for r in caplog.records)
