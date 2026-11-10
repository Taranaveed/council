"""Production must refuse to start with an insecure JWT_SECRET."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _run_import(*, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("JWT_SECRET", "RENDER", "ENV", "ENVIRONMENT")}
    env.update(extra_env)
    env["PYTHONPATH"] = str(BACKEND)
    env["ALERTS_SCHEDULER"] = "0"
    code = "import app.core.auth"  # raises at import if production + bad secret
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_jwt_secret_required_when_render_set():
    proc = _run_import(extra_env={"RENDER": "true"})
    assert proc.returncode != 0
    blob = (proc.stderr or "") + (proc.stdout or "")
    assert "JWT_SECRET" in blob


def test_jwt_secret_ok_with_long_secret_in_production():
    proc = _run_import(
        extra_env={
            "RENDER": "true",
            "JWT_SECRET": "production-secret-at-least-32-chars-long!!",
        }
    )
    assert proc.returncode == 0, proc.stderr
