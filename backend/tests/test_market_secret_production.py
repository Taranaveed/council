"""Production must refuse to start without MARKET_SERVICE_SECRET."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _run(code: str, *, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "JWT_SECRET",
            "MARKET_SERVICE_SECRET",
            "RENDER",
            "ENV",
            "ENVIRONMENT",
        )
    }
    env.update(extra_env)
    env["PYTHONPATH"] = str(BACKEND)
    env["ALERTS_SCHEDULER"] = "0"
    # Satisfy JWT guard when pretending to be production.
    env.setdefault(
        "JWT_SECRET",
        "production-secret-at-least-32-chars-long!!",
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_backend_refuses_missing_market_secret_in_production():
    proc = _run(
        "from app.core.prod_env import require_market_service_secret_in_production; "
        "require_market_service_secret_in_production()",
        extra_env={"RENDER": "true"},
    )
    assert proc.returncode != 0
    blob = (proc.stderr or "") + (proc.stdout or "")
    assert "MARKET_SERVICE_SECRET" in blob


def test_backend_refuses_short_market_secret_in_production():
    proc = _run(
        "from app.core.prod_env import require_market_service_secret_in_production; "
        "require_market_service_secret_in_production()",
        extra_env={"ENV": "production", "MARKET_SERVICE_SECRET": "short"},
    )
    assert proc.returncode != 0
    assert "MARKET_SERVICE_SECRET" in ((proc.stderr or "") + (proc.stdout or ""))


def test_backend_allows_long_market_secret_in_production():
    proc = _run(
        "from app.core.prod_env import require_market_service_secret_in_production; "
        "require_market_service_secret_in_production()",
        extra_env={
            "RENDER": "true",
            "MARKET_SERVICE_SECRET": "x" * 24,
        },
    )
    assert proc.returncode == 0, proc.stderr


def test_backend_allows_missing_market_secret_outside_production():
    proc = _run(
        "from app.core.prod_env import require_market_service_secret_in_production; "
        "require_market_service_secret_in_production()",
        extra_env={},
    )
    assert proc.returncode == 0, proc.stderr
