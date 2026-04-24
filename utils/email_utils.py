import os
import smtplib
from email.mime.text import MIMEText

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))


def _get_credentials():
    try:
        return os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_PASSWORD"]
    except KeyError as missing:
        raise RuntimeError(
            f"Missing required email env var: {missing}. "
            f"Copy .env.example to .env and set EMAIL_ADDRESS / EMAIL_PASSWORD."
        ) from None


def _send(to_email, subject, body):
    sender, password = _get_credentials()
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)


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
