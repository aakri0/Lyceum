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
