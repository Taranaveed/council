"""Optional SMTP email for deal alerts / reorder reminders."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any


def email_configured() -> bool:
    return bool(
        (os.getenv("ALERT_EMAIL_ENABLED") or "").strip().lower()
        in ("1", "true", "yes", "on")
        and (os.getenv("SMTP_HOST") or "").strip()
        and (os.getenv("SMTP_FROM") or "").strip()
    )


def send_alert_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    unsubscribe_url: str,
) -> dict[str, Any]:
    """
    Send a plain-text alert email when SMTP_* is configured.
    Returns {ok, skipped?, error?}.
    """
    to = (to_email or "").strip()
    if not to or "@" not in to:
        return {"ok": False, "error": "bad_recipient"}
    if not email_configured():
        return {"ok": False, "skipped": True, "reason": "smtp_not_configured"}

    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int(os.getenv("SMTP_PORT") or "587")
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    from_addr = (os.getenv("SMTP_FROM") or "").strip()
    use_tls = (os.getenv("SMTP_TLS") or "1").strip().lower() not in ("0", "false", "no")

    msg = EmailMessage()
    msg["Subject"] = subject[:180]
    msg["From"] = from_addr
    msg["To"] = to
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=12) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
