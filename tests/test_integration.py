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


def test_audit_logged_on_dept_create(_live_mysql, client, seeded_admin, db_conn):
    """Creating a department via /admin_add_department should write a row
    to audit_logs with the admin's user_id, the IP, and a User-Agent.
    """
    user_id, email, password = seeded_admin

    # Skip the real OTP exchange — simulate post-OTP state by writing the
    # session directly via Flask's test session_transaction.
    with client.session_transaction() as s:
        s["user_id"] = user_id
        s["role"] = "admin"

    resp = client.get("/admin_manage_departments")
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', resp.get_data(as_text=True))
    assert csrf, "CSRF token missing on departments page"

    new_name = f"TestDept-{user_id}"
    resp = client.post(
        "/admin_add_department",
        data={"dept_name": new_name, "csrf_token": csrf.group(1)},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    cur = db_conn.cursor(dictionary=True)
    cur.execute(
        "SELECT action, ip_address, user_agent FROM audit_logs "
        "WHERE user_id=%s AND action LIKE %s ORDER BY log_id DESC LIMIT 1",
        (user_id, f"%({new_name})%"),
    )
    row = cur.fetchone()
    cur.execute("DELETE FROM audit_logs WHERE action LIKE %s", (f"%({new_name})%",))
    cur.execute("DELETE FROM departments WHERE dept_name=%s", (new_name,))
    db_conn.commit()
    cur.close()

    assert row is not None, "audit_logs should have an entry for the dept create"
    assert "Created department_id" in row["action"]
    assert row["ip_address"], "IP should be captured"
    assert row["user_agent"], "User-Agent should be captured"


def test_audit_logs_pagination(_live_mysql, client, seeded_admin, db_conn):
    """/admin_audit_logs should respect ?per_page= and never return more
    rows than requested.

    Strategy: clear audit_logs first so the seeded markers are the *only*
    rows, then seed 3 and verify page 1 (per_page=2) shows 2 and page 2
    shows the 3rd. This avoids brittleness from earlier tests' rows.
    """
    user_id, email, password = seeded_admin

    cur = db_conn.cursor()
    cur.execute("DELETE FROM audit_logs")
    for i in range(3):
        cur.execute(
            "INSERT INTO audit_logs (user_id, action, ip_address, user_agent) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, f"pagination-test-{i}", "127.0.0.1", "pytest"),
        )
    db_conn.commit()
    cur.close()

    with client.session_transaction() as s:
        s["user_id"] = user_id
        s["role"] = "admin"

    resp = client.get("/admin_audit_logs?per_page=2&page=1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    page1_hits = sum(f"pagination-test-{i}" in body for i in range(3))
    assert page1_hits == 2, f"per_page=2 should show exactly 2 markers, saw {page1_hits}"

    resp2 = client.get("/admin_audit_logs?per_page=2&page=2")
    body2 = resp2.get_data(as_text=True)
    page2_hits = sum(f"pagination-test-{i}" in body2 for i in range(3))
    assert page2_hits == 1, f"page 2 should hold the remaining 1 marker, saw {page2_hits}"

    cur = db_conn.cursor()
    cur.execute("DELETE FROM audit_logs WHERE action LIKE 'pagination-test-%'")
    db_conn.commit()
    cur.close()


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
