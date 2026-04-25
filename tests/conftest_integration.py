"""Shared fixtures for integration tests that require a live MySQL.

Tests using these fixtures are SKIPPED when MySQL isn't reachable, so
``pytest`` still passes on a dev machine without a server. Set the
following env vars (or rely on .env) to point at a disposable test DB:

    DB_HOST   (default: 127.0.0.1)
    DB_PORT   (default: 3306)
    DB_USER   (default: root)
    DB_PASSWORD
    TEST_DB_NAME   (default: ERP_TEST_<pid>)

The fixture creates the schema fresh, seeds a small set of users, runs
the test, then DROPs the database. Schema is loaded from sql/schema.sql
plus everything in sql/migrations/.
"""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = REPO_ROOT / "sql" / "schema.sql"
MIGRATIONS_DIR = REPO_ROOT / "sql" / "migrations"


def _mysql_reachable() -> bool:
    host = os.environ.get("DB_HOST", "127.0.0.1")
    port = int(os.environ.get("DB_PORT", "3306"))
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


# Module-level skip: anything that imports this conftest is integration-only.
pytestmark = pytest.mark.skipif(
    not _mysql_reachable(),
    reason="MySQL not reachable on DB_HOST:DB_PORT — integration tests skipped",
)


def _split_statements(sql: str) -> list[str]:
    """Crude statement splitter for our schema.sql + migrations.

    Strips line comments only. ``/*! ... */`` conditional comments are
    preserved because they carry functional directives like
    ``FOREIGN_KEY_CHECKS=0`` that the schema dump relies on. Do NOT use
    this on arbitrary SQL — it does not handle semicolons inside string
    literals or DELIMITER blocks.
    """
    sql = re.sub(r"^\s*--.*$", "", sql, flags=re.MULTILINE)
    return [s.strip() for s in sql.split(";") if s.strip()]


@pytest.fixture(scope="session")
def test_db_name() -> str:
    return os.environ.get("TEST_DB_NAME", f"ERP_TEST_{os.getpid()}")


@pytest.fixture(scope="session")
def _live_mysql(test_db_name):
    """Create a fresh test DB, load schema + migrations, drop it after."""
    import mysql.connector

    cfg = {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
    }

    admin = mysql.connector.connect(**cfg)
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{test_db_name}`")
    cur.execute(f"CREATE DATABASE `{test_db_name}` CHARACTER SET utf8mb4")
    cur.close()
    admin.close()

    # Re-connect with the DB selected so multi-statement loading works.
    # consume_results=True drains any rows from SET/SHOW etc. so the next
    # execute() doesn't hit "Unread result found".
    conn = mysql.connector.connect(database=test_db_name, consume_results=True, **cfg)
    cur = conn.cursor()

    def _exec_file(text: str) -> None:
        for stmt in _split_statements(text):
            try:
                cur.execute(stmt)
                # Drain any leftover result set (defensive — consume_results
                # already handles this, but old connector versions don't).
                if cur.with_rows:
                    cur.fetchall()
            except mysql.connector.Error:
                pass

    _exec_file(SCHEMA_FILE.read_text())
    if MIGRATIONS_DIR.exists():
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            _exec_file(path.read_text())

    conn.commit()
    cur.close()
    conn.close()

    # Point the app at the test DB for the duration of the session.
    prev = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = test_db_name
    yield test_db_name
    if prev is None:
        del os.environ["DB_NAME"]
    else:
        os.environ["DB_NAME"] = prev

    admin = mysql.connector.connect(**cfg)
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{test_db_name}`")
    cur.close()
    admin.close()


@pytest.fixture
def db_conn(_live_mysql):
    """Per-test connection. Caller is responsible for cleanup of rows."""
    import mysql.connector

    conn = mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=_live_mysql,
    )
    yield conn
    conn.close()


@pytest.fixture
def seeded_admin(db_conn):
    """Create a single admin user; returns (user_id, email, plain_password)."""
    from flask_bcrypt import generate_password_hash

    email = "admin-test@example.com"
    password = "test-pass-1234"
    hashed = generate_password_hash(password, rounds=4).decode()

    cur = db_conn.cursor()
    cur.execute("DELETE FROM users WHERE email=%s", (email,))
    cur.execute(
        "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, 'admin')",
        ("Test Admin", email, hashed),
    )
    user_id = cur.lastrowid
    db_conn.commit()
    cur.close()

    yield user_id, email, password

    cur = db_conn.cursor()
    cur.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
    db_conn.commit()
    cur.close()
