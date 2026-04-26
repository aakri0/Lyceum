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


def test_request_id_header_echoed(client):
    """Every response should carry an X-Request-Id (minted or echoed)."""
    resp = client.get("/")
    assert resp.headers.get("X-Request-Id"), "X-Request-Id missing on response"

    resp2 = client.get("/", headers={"X-Request-Id": "rid-test-12345"})
    assert resp2.headers.get("X-Request-Id") == "rid-test-12345", (
        "Inbound X-Request-Id should be echoed verbatim"
    )


def test_password_complexity_rejects_common_password():
    """ResetPasswordForm should refuse top-list passwords even when long."""
    from werkzeug.datastructures import MultiDict
    from forms import ResetPasswordForm

    form = ResetPasswordForm(MultiDict({
        "password": "password123",
        "confirm": "password123",
    }))
    assert not form.validate()
    assert any(
        "common" in err.lower() or "breached" in err.lower()
        for err in form.password.errors
    )


def test_password_complexity_rejects_pure_letters():
    from werkzeug.datastructures import MultiDict
    from forms import ResetPasswordForm

    form = ResetPasswordForm(MultiDict({
        "password": "onlyletters",
        "confirm": "onlyletters",
    }))
    assert not form.validate()


def test_password_complexity_accepts_mixed_strong_password():
    from werkzeug.datastructures import MultiDict
    from forms import ResetPasswordForm

    form = ResetPasswordForm(MultiDict({
        "password": "MyStrong!Pass9",
        "confirm": "MyStrong!Pass9",
    }))
    assert form.validate(), form.errors


def test_phase4_routes_registered(client):
    """All phase-4 endpoints should be importable + registered."""
    expected = {
        "/admin_course_allotment", "/admin_announcements",
        "/faculty_attendance/<int:section_id>",
        "/faculty_materials/<int:course_id>",
        "/faculty_bulk_grades/<int:section_id>",
        "/student_attendance", "/student_materials", "/student_export",
        "/notifications", "/change_password",
        "/request/<int:req_id>",
        "/profile_photo/<filename>",
        "/bonafide/<path:serial_no>",
    }
    from app import app as flask_app
    rules = {r.rule for r in flask_app.url_map.iter_rules()}
    missing = expected - rules
    assert not missing, f"missing routes: {missing}"


def test_routes_registered_on_main_module(client):
    """Regression: routes/*.py must register on the same Flask instance
    that ``app.run()`` serves. If someone removes the
    ``sys.modules.setdefault('app', ...)`` shim at the top of app.py,
    running ``python app.py`` ends up serving an empty app and every URL
    404s. Hitting ``/student_login`` here proves the alias is still in
    place — it lives in routes/student.py, so a 404 means the alias broke.
    """
    resp = client.get("/student_login")
    assert resp.status_code == 200, (
        "GET /student_login 404'd — likely the sys.modules['app'] alias at "
        "the top of app.py is missing. routes/*.py would then register on a "
        "duplicate Flask instance that the server never sees."
    )
