"""SIGNUP_CODE invite gate for registration."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("ALERTS_SCHEDULER", "0")
    monkeypatch.delenv("SIGNUP_CODE", raising=False)
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_register_open_when_signup_code_unset(client):
    email = f"open_{uuid.uuid4().hex[:10]}@example.com"
    res = client.post(
        "/auth/register",
        json={"email": email, "password": "TestPass123!"},
    )
    assert res.status_code == 200
    assert res.json()["access_token"]


def test_register_requires_code_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("ALERTS_SCHEDULER", "0")
    monkeypatch.setenv("SIGNUP_CODE", "tester-invite-42")
    from app.main import app

    with TestClient(app) as client:
        email = f"need_{uuid.uuid4().hex[:10]}@example.com"
        missing = client.post(
            "/auth/register",
            json={"email": email, "password": "TestPass123!"},
        )
        assert missing.status_code == 403
        assert "invite code" in missing.json()["detail"].lower()

        wrong = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "TestPass123!",
                "signup_code": "wrong",
            },
        )
        assert wrong.status_code == 403
        assert "not valid" in wrong.json()["detail"].lower()

        ok = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "TestPass123!",
                "signup_code": "tester-invite-42",
            },
        )
        assert ok.status_code == 200
        assert ok.json()["access_token"]
