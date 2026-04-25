import logging
import os
import smtplib
import threading
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "15"))


def _get_credentials():
    try:
        return os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_PASSWORD"]
    except KeyError as missing:
        raise RuntimeError(
            f"Missing required email env var: {missing}. "
            f"Copy .env.example to .env and set EMAIL_ADDRESS / EMAIL_PASSWORD."
        ) from None


def _send_sync(to_email, subject, body):
    sender, password = _get_credentials()
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)


def _send(to_email, subject, body):
    """Fire-and-forget email send.

    Runs the SMTP transaction on a daemon thread so a slow upstream (Gmail
    occasionally takes 5–15s) does not block the request worker. Set
    EMAIL_SEND_SYNC=1 in tests to send synchronously and surface errors.
    """
    if os.environ.get("EMAIL_SEND_SYNC") == "1":
        _send_sync(to_email, subject, body)
        return

    def _worker():
        try:
            _send_sync(to_email, subject, body)
        except Exception:
            logger.exception("Failed to send email to %s (subject=%r)", to_email, subject)

    threading.Thread(target=_worker, daemon=True, name="smtp-send").start()


def send_otp_email(to_email, otp):
    body = f"Your ERP login OTP is: {otp}\n\nValid for 5 minutes."
    _send(to_email, "ERP Login OTP", body)


def send_password_reset_email(to_email, reset_link):
    body = (
        "You requested a password reset for your ERP account.\n\n"
        f"Click the link below to reset your password:\n{reset_link}\n\n"
        "This link is valid for 15 minutes.\n\n"
        "If you did not request this reset, please ignore this email."
    )
    _send(to_email, "ERP Password Reset Request", body)
