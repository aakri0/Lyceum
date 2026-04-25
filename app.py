import csv
import io
import logging
import os
import random
import secrets
import sys
import uuid
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

# When run directly (`python app.py`), this module is loaded as ``__main__``.
# routes/*.py do ``from app import app`` — without this alias Python would
# import a SECOND copy of this file as module ``app``, registering every
# @app.route on a duplicate Flask instance that ``app.run()`` never serves
# (you'd get 404 on every URL despite the routes being "defined"). Pinning
# the alias here makes ``from app import app`` resolve to this same module
# whether we're __main__ or imported. No-op when already imported as ``app``.
sys.modules.setdefault("app", sys.modules[__name__])

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

class _RequestIdFilter(logging.Filter):
    """Inject ``request_id`` into every log record.

    Pulled from ``flask.g`` when inside a request, otherwise '-'. This lets
    a single log line tie back to the request that produced it; pair with
    the ``X-Request-Id`` response header to follow a user's report through
    the logs.
    """

    def filter(self, record):
        rid = "-"
        try:
            from flask import g, has_app_context
            if has_app_context():
                rid = getattr(g, "request_id", "-") or "-"
        except Exception:
            pass
        record.request_id = rid
        return True


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
)
for _h in logging.getLogger().handlers:
    _h.addFilter(_RequestIdFilter())
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


@app.before_request
def _assign_request_id():
    """Mint or accept a request ID for log correlation.

    Honours an inbound ``X-Request-Id`` header (when behind a proxy or
    load balancer that adds one) so the same ID flows through every layer.
    Otherwise generates a fresh UUID4. Stored on ``flask.g`` for the
    logging filter.
    """
    from flask import g
    incoming = request.headers.get("X-Request-Id", "").strip()
    g.request_id = incoming[:64] if incoming else uuid.uuid4().hex[:16]


@app.after_request
def _echo_request_id(response):
    from flask import g
    rid = getattr(g, "request_id", None)
    if rid:
        response.headers.setdefault("X-Request-Id", rid)
    return response


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


def _paginate(default_per_page=50, max_per_page=200):
    """Parse ?page=&per_page= query params into (page, per_page, offset).

    Defaults are sensible for admin list pages; max is capped to keep a
    rogue ``?per_page=999999`` from melting the DB.
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(max_per_page, max(1, int(request.args.get("per_page", default_per_page))))
    except (TypeError, ValueError):
        per_page = default_per_page
    return page, per_page, (page - 1) * per_page


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
