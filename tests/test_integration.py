"""Integration tests against a live MySQL test database.

Skipped automatically when MySQL isn't reachable. Importing
``conftest_integration`` brings in the ``_live_mysql`` and ``db_conn``
fixtures plus the module-level skipif.
"""

from __future__ import annotations

import re

from .conftest_integration import (  # noqa: F401  (fixtures + skipif)
    _live_mysql,
    db_conn,
    pytestmark,
    seeded_admin,
    test_db_name,
)


def test_db_schema_loaded(_live_mysql, db_conn):
    """Sanity: the test DB has the core tables we expect."""
    cur = db_conn.cursor()
    cur.execute("SHOW TABLES")
    tables = {row[0] for row in cur.fetchall()}
    cur.close()
    assert {"users", "students", "faculty", "audit_logs", "swd_requests"} <= tables


def test_audit_logs_has_ip_ua_columns(_live_mysql, db_conn):
    """The IP+UA migration must apply cleanly to the schema."""
    cur = db_conn.cursor()
    cur.execute("DESCRIBE audit_logs")
    cols = {row[0] for row in cur.fetchall()}
    cur.close()
    assert "ip_address" in cols, "Migration 001 didn't add ip_address column"
    assert "user_agent" in cols, "Migration 001 didn't add user_agent column"


def test_admin_login_flow_sends_otp(_live_mysql, client, seeded_admin, db_conn, monkeypatch):
    """A valid admin login should clear old OTPs, store a new one, and redirect."""
    user_id, email, password = seeded_admin

    sent = []
    monkeypatch.setattr(
        "routes.admin.send_otp_email",
        lambda to, otp: sent.append((to, otp)),
    )

    resp = client.get("/admin_login")  # prime CSRF cookie if any
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', resp.get_data(as_text=True))
    assert csrf, "CSRF token not present on admin_login GET"

    resp = client.post(
        "/admin_login",
        data={"email": email, "password": password, "csrf_token": csrf.group(1)},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/verify_otp")
    assert sent and sent[0][0] == email

    cur = db_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM otp_verification WHERE user_id=%s", (user_id,))
    (count,) = cur.fetchone()
    cur.execute("DELETE FROM otp_verification WHERE user_id=%s", (user_id,))
    db_conn.commit()
    cur.close()
    assert count == 1


def test_admin_login_rejects_bad_password(_live_mysql, client, seeded_admin):
    user_id, email, _ = seeded_admin

    resp = client.get("/admin_login")
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', resp.get_data(as_text=True))

    resp = client.post(
        "/admin_login",
        data={"email": email, "password": "wrong-password", "csrf_token": csrf.group(1)},
        follow_redirects=False,
    )
    # Stays on login page (200) with a flashed error rather than redirecting.
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lower()
    assert "invalid" in body or "credential" in body
