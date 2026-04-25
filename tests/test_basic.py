"""Smoke tests that run without a live database.

These cover the app's own contract — security headers, CSRF, rate limits,
the health endpoint when DB is unreachable. Anything that touches MySQL
should live in a separate `test_integration.py` guarded by a fixture that
spins up a test schema.
"""

from unittest.mock import patch


def test_home_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_security_headers_present(client):
    resp = client.get("/")
    assert "Content-Security-Policy" in resp.headers
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Referrer-Policy" in resp.headers
    assert "X-Content-Type-Options" in resp.headers


def test_csrf_rejects_post_without_token(client):
    resp = client.post("/student_login", data={"email": "x@y.com", "password": "z"})
    assert resp.status_code == 400


def test_healthz_reports_db_failure(client):
    """When MySQL is unreachable, /healthz returns 503 with a JSON body."""
    with patch("routes.misc.get_connection", return_value=None):
        resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.is_json
    assert resp.get_json()["status"] == "error"


def test_healthz_ok_when_db_up(client):
    """Mock a healthy DB connection and assert 200 OK."""
    fake_cur = type("C", (), {
        "execute": lambda self, *a, **k: None,
        "fetchone": lambda self: (1,),
        "close": lambda self: None,
    })()
    fake_conn = type("Conn", (), {
        "cursor": lambda self: fake_cur,
        "close": lambda self: None,
    })()
    with patch("routes.misc.get_connection", return_value=fake_conn):
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "db": "ok"}


def test_404_path(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
