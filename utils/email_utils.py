"""Outbound email helpers (OTP, password reset).

Sends are dispatched on a daemon thread by default so a slow Gmail
upstream cannot stall a request worker. Set ``EMAIL_SEND_SYNC=1`` for
test environments where you need failures to surface synchronously.

Bodies are rendered from Jinja templates under ``frontend/emails/``,
using the Flask app's Jinja environment when available so any future
filters/macros work the same way as page templates. Falls back to a
standalone Jinja Environment for CLI scripts that don't push an app
context.
"""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "15"))

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "frontend" / "emails"
_FALLBACK_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _render(template_name: str, **context) -> str:
    """Render an email template using Flask's env if available."""
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            return current_app.jinja_env.get_template(
                f"emails/{template_name}"
            ).render(**context)
    except Exception:
        pass
    return _FALLBACK_ENV.get_template(template_name).render(**context)


def _get_credentials():
    try:
        return os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_PASSWORD"]
    except KeyError as missing:
        raise RuntimeError(
            f"Missing required email env var: {missing}. "
            f"Copy .env.example to .env and set EMAIL_ADDRESS / EMAIL_PASSWORD."
        ) from None


def _send_sync(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    sender, password = _get_credentials()
    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(text_body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)


def _send(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Fire-and-forget email send.

    Runs the SMTP transaction on a daemon thread so a slow upstream (Gmail
    occasionally takes 5–15s) does not block the request worker. Set
    ``EMAIL_SEND_SYNC=1`` in tests to send synchronously and surface errors.
    """
    if os.environ.get("EMAIL_SEND_SYNC") == "1":
        _send_sync(to_email, subject, text_body, html_body)
        return

    def _worker():
        try:
            _send_sync(to_email, subject, text_body, html_body)
        except Exception:
            logger.exception("Failed to send email to %s (subject=%r)", to_email, subject)

    threading.Thread(target=_worker, daemon=True, name="smtp-send").start()


def send_otp_email(to_email: str, otp: str) -> None:
    text = _render("otp.txt", otp=otp)
    html = _render("otp.html", otp=otp)
    _send(to_email, "ERP Login OTP", text, html)


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    text = _render("password_reset.txt", reset_link=reset_link)
    html = _render("password_reset.html", reset_link=reset_link)
    _send(to_email, "ERP Password Reset Request", text, html)
