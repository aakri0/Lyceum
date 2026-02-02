import smtplib
from email.mime.text import MIMEText

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL = "dbms.college.erp@gmail.com"
PASSWORD = "REDACTED_GMAIL_APP_PASSWORD"  # Gmail App Password

def send_otp_email(to_email, otp):
    msg = MIMEText(f"Your ERP login OTP is: {otp}\n\nValid for 5 minutes.")
    msg["Subject"] = "ERP Login OTP"
    msg["From"] = EMAIL
    msg["To"] = to_email

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(EMAIL, PASSWORD)
    server.send_message(msg)
    server.quit()

def send_password_reset_email(to_email, reset_link):
    msg = MIMEText(f"You requested a password reset for your ERP account.\n\nClick the link below to reset your password:\n{reset_link}\n\nThis link is valid for 15 minutes.\n\nIf you did not request this reset, please ignore this email.")
    msg["Subject"] = "ERP Password Reset Request"
    msg["From"] = EMAIL
    msg["To"] = to_email

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(EMAIL, PASSWORD)
    server.send_message(msg)
    server.quit()
