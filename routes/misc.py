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


# =============================================================
# NOTIFICATIONS (B2)
# =============================================================
@app.route('/notifications')
def notifications():
    """List all notifications for the current user; auto-marks as read."""
    if not session.get('user_id'):
        return redirect(url_for('home'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT notification_id, kind, message, link, read_at, created_at
        FROM notifications
        WHERE user_id=%s
        ORDER BY created_at DESC
        LIMIT 100
    """, (session['user_id'],))
    items = cur.fetchall()
    # Mark everything we just rendered as read.
    cur.execute(
        "UPDATE notifications SET read_at=CURRENT_TIMESTAMP "
        "WHERE user_id=%s AND read_at IS NULL",
        (session['user_id'],),
    )
    conn.commit()
    conn.close()
    return render_template('notifications.html', items=items)


@app.route('/notifications/mark_read/<int:nid>', methods=['POST'])
def notification_mark_read(nid):
    if not session.get('user_id'):
        return redirect(url_for('home'))
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE notifications SET read_at=CURRENT_TIMESTAMP "
        "WHERE notification_id=%s AND user_id=%s",
        (nid, session['user_id']),
    )
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('notifications'))


# =============================================================
# SWD REQUEST DETAIL + COMMENTS (A7)
# =============================================================
@app.route('/request/<int:req_id>')
def request_detail(req_id):
    """Single request page with timeline + comment form.

    Visible to: the request owner (student), the assigned faculty, and any
    admin. Faculty without an assignment for this request can't see it.
    """
    if not session.get('user_id'):
        return redirect(url_for('home'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT r.req_id, r.category, r.description, r.status, r.created_at,
               r.assigned_faculty_id, r.student_id,
               s.roll_no, su.user_id AS student_user_id, su.name AS student_name,
               fu.name AS faculty_name
        FROM swd_requests r
        JOIN students s ON r.student_id = s.student_id
        JOIN users su ON s.user_id = su.user_id
        LEFT JOIN faculty f ON r.assigned_faculty_id = f.faculty_id
        LEFT JOIN users fu ON f.user_id = fu.user_id
        WHERE r.req_id = %s
    """, (req_id,))
    req = cur.fetchone()
    if not req:
        conn.close()
        flash("Request not found.", "danger")
        return redirect(url_for('home'))

    role = session.get('role')
    user_id = session['user_id']
    allowed = (
        role == 'admin'
        or req['student_user_id'] == user_id
        or (role == 'faculty' and session.get('faculty_id') == req['assigned_faculty_id'])
    )
    if not allowed:
        conn.close()
        flash("You don't have access to this request.", "danger")
        return redirect(url_for('home'))

    cur.execute("""
        SELECT c.comment_id, c.user_id, c.body, c.event_kind, c.created_at,
               u.name, u.role
        FROM swd_comments c
        LEFT JOIN users u ON c.user_id = u.user_id
        WHERE c.req_id = %s
        ORDER BY c.created_at ASC
    """, (req_id,))
    timeline = cur.fetchall()
    conn.close()
    return render_template('request_detail.html', req=req, timeline=timeline)


@app.route('/request/<int:req_id>/comment', methods=['POST'])
def request_comment(req_id):
    if not session.get('user_id'):
        return redirect(url_for('home'))

    from forms import SWDCommentForm
    form = SWDCommentForm(request.form)
    if not form.validate():
        flash("Comment cannot be empty.", "danger")
        return redirect(url_for('request_detail', req_id=req_id))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT r.assigned_faculty_id, su.user_id AS student_user_id, r.category
        FROM swd_requests r
        JOIN students s ON r.student_id = s.student_id
        JOIN users su ON s.user_id = su.user_id
        WHERE r.req_id = %s
    """, (req_id,))
    req = cur.fetchone()
    if not req:
        conn.close()
        flash("Request not found.", "danger")
        return redirect(url_for('home'))

    role = session.get('role')
    user_id = session['user_id']
    allowed = (
        role == 'admin'
        or req['student_user_id'] == user_id
        or (role == 'faculty' and session.get('faculty_id') == req['assigned_faculty_id'])
    )
    if not allowed:
        conn.close()
        flash("Not allowed.", "danger")
        return redirect(url_for('home'))

    cur.execute(
        "INSERT INTO swd_comments (req_id, user_id, body, event_kind) "
        "VALUES (%s, %s, %s, 'comment')",
        (req_id, user_id, form.body.data.strip()),
    )

    # Notify the *other* parties on the thread (everyone with access who
    # isn't the commenter).
    targets = set()
    if req['student_user_id'] != user_id:
        targets.add(req['student_user_id'])
    if req['assigned_faculty_id']:
        cur.execute(
            "SELECT u.user_id FROM faculty f JOIN users u ON f.user_id = u.user_id "
            "WHERE f.faculty_id = %s",
            (req['assigned_faculty_id'],),
        )
        row = cur.fetchone()
        if row and row['user_id'] != user_id:
            targets.add(row['user_id'])
    for tid in targets:
        # _notify is in app.py; import locally to avoid touching this file's import order.
        from app import _notify
        _notify(
            cur, tid, 'request_comment',
            f"New comment on your {req['category']} request.",
            url_for('request_detail', req_id=req_id),
        )

    conn.commit()
    conn.close()
    return redirect(url_for('request_detail', req_id=req_id))


# =============================================================
# CHANGE PASSWORD (A9)
# =============================================================
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    """Logged-in user changes their own password.

    Distinct from /reset_password (which requires an emailed token):
    here we verify the current password instead. Same complexity rules
    apply via the shared policy mixin.
    """
    if not session.get('user_id'):
        return redirect(url_for('home'))

    from forms import ChangePasswordForm
    if request.method == 'POST':
        form = ChangePasswordForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            return render_template('change_password.html')

        from app import _audit, bcrypt
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT password FROM users WHERE user_id=%s", (session['user_id'],))
        row = cur.fetchone()
        if not row or not bcrypt.check_password_hash(row['password'], form.current_password.data):
            conn.close()
            flash("Current password is incorrect.", "danger")
            return render_template('change_password.html')

        new_hash = bcrypt.generate_password_hash(form.password.data).decode()
        cur.execute("UPDATE users SET password=%s WHERE user_id=%s",
                    (new_hash, session['user_id']))
        _audit(cur, session['user_id'], "Password changed via /change_password")
        conn.commit()
        conn.close()
        flash("Password changed.", "success")
        return redirect(url_for('home'))

    return render_template('change_password.html')


# =============================================================
# PROFILE PHOTO (C7)
# =============================================================
import mimetypes as _mime
import os as _os2
import uuid as _uuid2
from pathlib import Path as _Path2

from flask import abort as _abort2, send_from_directory as _send_from_directory
from werkzeug.utils import secure_filename as _secure_filename

_ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def _avatar_dir() -> _Path2:
    p = _Path2(_os2.environ.get("UPLOAD_DIR", "./uploads")).resolve() / "avatars"
    p.mkdir(parents=True, exist_ok=True)
    return p


@app.route('/profile_photo/upload', methods=['POST'])
def profile_photo_upload():
    if not session.get('user_id'):
        return redirect(url_for('home'))

    f = request.files.get('avatar')
    if not f or not f.filename:
        flash("Choose an image first.", "danger")
        return redirect(request.referrer or url_for('home'))

    safe = _secure_filename(f.filename)
    ext = _os2.path.splitext(safe)[1].lower()
    if ext not in _ALLOWED_AVATAR_EXT:
        flash("Only PNG, JPG, GIF, or WebP allowed.", "danger")
        return redirect(request.referrer or url_for('home'))

    mime = (f.mimetype or _mime.guess_type(safe)[0] or "")
    if not mime.startswith("image/"):
        flash("File doesn't look like an image.", "danger")
        return redirect(request.referrer or url_for('home'))

    unique = f"u{session['user_id']}_{_uuid2.uuid4().hex[:8]}{ext}"
    dest = _avatar_dir() / unique
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = f.stream.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > _AVATAR_MAX_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                flash("Image too large (max 2 MB).", "danger")
                return redirect(request.referrer or url_for('home'))
            out.write(chunk)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT profile_photo FROM users WHERE user_id=%s", (session['user_id'],))
    prev = cur.fetchone()
    cur.execute("UPDATE users SET profile_photo=%s WHERE user_id=%s",
                (unique, session['user_id']))
    from app import _audit
    _audit(cur, session['user_id'], "Updated profile photo")
    conn.commit()
    conn.close()

    if prev and prev.get('profile_photo'):
        try:
            (_avatar_dir() / prev['profile_photo']).unlink(missing_ok=True)
        except Exception:
            logger.exception("orphan avatar cleanup failed")

    flash("Profile photo updated.", "success")
    return redirect(request.referrer or url_for('home'))


@app.route('/profile_photo/<filename>')
def profile_photo(filename):
    """Public-ish (login-gated) avatar fetch. Filename comes from DB so
    it's already trusted; just ensure it stays inside the avatars dir.
    """
    if not session.get('user_id'):
        _abort2(403)
    if "/" in filename or "\\" in filename or filename.startswith("."):
        _abort2(400)
    return _send_from_directory(_avatar_dir(), filename)
