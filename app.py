import csv
import io
import logging
import os
import random
import secrets
import uuid
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from mysql.connector import Error

from db import close_tracked_connections, get_connection
from forms import ForgotPasswordForm, LoginForm, OTPForm, ResetPasswordForm
from utils.email_utils import send_otp_email, send_password_reset_email

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='frontend')
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is not set. Copy .env.example to .env and set a strong "
        "random value (e.g. `openssl rand -hex 32`)."
    )

# Session cookie hardening. SECURE defaults to off for local dev; set
# SESSION_COOKIE_SECURE=1 in production (requires HTTPS).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    WTF_CSRF_TIME_LIMIT=None,  # token lives as long as the session
    BCRYPT_LOG_ROUNDS=int(os.environ.get("BCRYPT_LOG_ROUNDS", "12")),
)

csrf = CSRFProtect(app)

# Security headers. Chart.js is loaded from a CDN, so script-src allows it
# explicitly; everything else stays self-only. force_https mirrors
# SESSION_COOKIE_SECURE so local HTTP dev is unaffected.
Talisman(
    app,
    force_https=app.config["SESSION_COOKIE_SECURE"],
    strict_transport_security=app.config["SESSION_COOKIE_SECURE"],
    session_cookie_secure=app.config["SESSION_COOKIE_SECURE"],
    content_security_policy={
        "default-src": "'self'",
        "script-src": ["'self'", "https://cdn.jsdelivr.net", "'unsafe-inline'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:"],
        "font-src": "'self'",
        "connect-src": "'self'",
        "frame-ancestors": "'none'",
    },
    referrer_policy="strict-origin-when-cross-origin",
    frame_options="DENY",
)

# Rate limiter. Defaults to in-memory storage — set RATELIMIT_STORAGE_URI
# (e.g. redis://localhost:6379) in production for a shared, persistent store.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    default_limits=[],
)


@app.teardown_appcontext
def _release_db_connections(exc):
    close_tracked_connections()

@app.template_filter('ordinal_year')
def ordinal_year_filter(year):
    if not year:
        return ""
    try:
        y = int(year)
        if y == 1: return "1st Year"
        if y == 2: return "2nd Year"
        if y == 3: return "3rd Year"
        return f"{y}th Year"
    except (ValueError, TypeError):
        return f"Year {year}"

bcrypt = Bcrypt(app)

def _audit(cur, user_id, action):
    """Insert an audit log row, capturing the request IP and user-agent."""
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or "")[:45]
    ua = (request.headers.get("User-Agent") or "")[:255]
    cur.execute(
        "INSERT INTO audit_logs (user_id, action, ip_address, user_agent) "
        "VALUES (%s, %s, %s, %s)",
        (user_id, action, ip, ua),
    )


# =============================================================
# HOME


# =============================================================
# Register route handlers. Imported at the bottom because each
# routes/*.py module does ``from app import app, ...`` — by this
# point those names are bound on the partially-initialised app
# module, so the cyclic import resolves cleanly.
# =============================================================
from routes import admin, auth, faculty, misc, student  # noqa: E402, F401



# =============================================================
# MAIN
# =============================================================
if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=debug)
