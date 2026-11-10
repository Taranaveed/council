"""Production environment guards and small helpers."""
from __future__ import annotations

import logging
import os

_log = logging.getLogger("uvicorn.error")

MARKET_SECRET_MIN_LEN = 24


def is_production() -> bool:
    return bool(
        os.getenv("RENDER")
        or os.getenv("ENV", "").lower() in ("production", "prod")
        or os.getenv("ENVIRONMENT", "").lower() in ("production", "prod")
    )


def market_service_secret() -> str:
    return (os.getenv("MARKET_SERVICE_SECRET") or "").strip()


def require_market_service_secret_in_production() -> None:
    """Refuse to start in production without a usable MARKET_SERVICE_SECRET."""
    if not is_production():
        return
    secret = market_service_secret()
    if not secret or len(secret) < MARKET_SECRET_MIN_LEN:
        raise RuntimeError(
            "MARKET_SERVICE_SECRET must be set to a shared secret of at least "
            f"{MARKET_SECRET_MIN_LEN} characters in production "
            "(same value on API and market-service). Refusing to start."
        )


def signup_is_open() -> bool:
    """True when SIGNUP_CODE is unset/empty (open registration)."""
    return not (os.getenv("SIGNUP_CODE") or "").strip()


def warn_if_signup_open_in_production() -> None:
    if is_production() and signup_is_open():
        _log.warning(
            "SIGNUP_CODE is unset — registration is OPEN. "
            "Set SIGNUP_CODE on the API before inviting testers."
        )


def free_briefs_exhausted_message(*, used: int | object, limit: int | object) -> str:
    contact = (os.getenv("SUPPORT_CONTACT") or "").strip()
    if not contact:
        contact = "the team"
    return (
        f"You've used all free briefs for this month ({used} of {limit}). "
        f"Contact {contact} for more."
    )
