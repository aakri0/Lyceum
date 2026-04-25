"""Public + infrastructure routes: home, health/readiness probes, logout.

Routes registered on the shared ``app`` object via ``@app.route``.
Endpoint names match function names so existing ``url_for`` calls in
templates continue to resolve unchanged.
"""

import os

from datetime import date, datetime, timedelta

from flask import (
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from mysql.connector import Error

from app import _audit, app, bcrypt, csrf, limiter, logger
from db import get_connection
from utils.email_utils import send_otp_email, send_password_reset_email


# =============================================================
@app.route('/')
def home():
    return render_template('home.html')


# =============================================================
# HEALTH CHECK (for load balancers / uptime probes)
# =============================================================
@app.route('/healthz')
@csrf.exempt
@limiter.exempt
def healthz():
    """Lightweight readiness probe: app is up and DB is reachable."""
    conn = get_connection()
    if conn is None:
        return jsonify(status="error", db="unreachable"), 503
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
    except Error:
        return jsonify(status="error", db="query_failed"), 503
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return jsonify(status="ok", db="ok"), 200


@app.route('/readyz')
@csrf.exempt
@limiter.exempt
def readyz():
    """Deeper readiness probe: DB + rate-limit backend + SMTP reachable.

    Returns 200 only if every dependency the running config relies on is
    reachable. SMTP and Redis are best-effort: if the env doesn't configure
    them, they're reported as ``"skipped"`` and don't fail the check.
    """
    status = {"db": "unknown", "redis": "skipped", "smtp": "skipped"}
    healthy = True

    # --- DB ---
    conn = get_connection()
    if conn is None:
        status["db"] = "unreachable"
        healthy = False
    else:
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            status["db"] = "ok"
        except Error:
            status["db"] = "query_failed"
            healthy = False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # --- Redis (rate-limit backend, only if configured) ---
    rl_uri = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    if rl_uri.startswith("redis://") or rl_uri.startswith("rediss://"):
        try:
            import redis  # local import; optional dep
            r = redis.Redis.from_url(rl_uri, socket_connect_timeout=2)
            r.ping()
            status["redis"] = "ok"
        except Exception:
            status["redis"] = "unreachable"
            healthy = False

    # --- SMTP (only if credentials are configured) ---
    if os.environ.get("EMAIL_ADDRESS") and os.environ.get("EMAIL_PASSWORD"):
        try:
            import smtplib
            host = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
            port = int(os.environ.get("SMTP_PORT", "587"))
            with smtplib.SMTP(host, port, timeout=3) as s:
                s.noop()
            status["smtp"] = "ok"
        except Exception:
            status["smtp"] = "unreachable"
            healthy = False

    return jsonify(status="ok" if healthy else "error", **status), (200 if healthy else 503)

# =============================================================


# =============================================================
# LOGOUT
# =============================================================
@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for('home'))
