"""MySQL connection factory backed by ``mysql-connector-python``'s pool.

Why a pool: every request opening a fresh TCP+TLS+auth handshake to MySQL
costs ~5-15ms on a healthy LAN and far more on a cold connection. With
a pool the request just leases an idle connection, so dashboards that
fire several short queries finish noticeably quicker, and the DB sees a
bounded connection count instead of one-per-concurrent-request.

Pool sizing: defaults to 10. mysql-connector caps the per-pool size at
32 — set ``DB_POOL_SIZE`` in env to override. Tune to roughly the
gunicorn worker count × concurrent-requests-per-worker, with a small
safety margin.

Standalone scripts (no Flask app context) and the test fixture also
work: they bypass the pool entirely so a one-shot script doesn't have
to remember to call ``conn.close()`` to return the connection.
"""

from __future__ import annotations

import logging
import os
import threading

import mysql.connector
from mysql.connector import Error
from mysql.connector.pooling import MySQLConnectionPool

logger = logging.getLogger(__name__)

_POOL: MySQLConnectionPool | None = None
_POOL_LOCK = threading.Lock()


def _build_pool() -> MySQLConnectionPool | None:
    """Construct the singleton connection pool.

    Returns ``None`` (instead of raising) on missing env vars / unreachable
    DB so health probes and CLI scripts can degrade gracefully.
    """
    try:
        return MySQLConnectionPool(
            pool_name="erp_pool",
            pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
            pool_reset_session=True,
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ.get("DB_NAME", "ERP"),
            autocommit=False,
        )
    except KeyError as missing:
        logger.error(
            "Missing required database env var: %s. "
            "Copy .env.example to .env and fill in credentials.",
            missing,
        )
        return None
    except Error:
        logger.exception("Failed to initialise MySQL connection pool")
        return None


def _get_pool() -> MySQLConnectionPool | None:
    global _POOL
    if _POOL is not None:
        return _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = _build_pool()
    return _POOL


def get_connection():
    """
    Lease a MySQL connection.

    When called inside a Flask request, the leased pooled connection is
    tracked on ``flask.g`` and returned to the pool at teardown — so a
    raised exception mid-route never leaks a slot. Standalone scripts
    (no app context) get a non-pooled, plain connection and remain
    responsible for closing it.
    """
    try:
        from flask import g, has_app_context
        in_request = has_app_context()
    except Exception:
        in_request = False

    if in_request:
        pool = _get_pool()
        if pool is None:
            return None
        try:
            connection = pool.get_connection()
        except Error:
            logger.exception("Failed to lease a pooled DB connection")
            return None

        from flask import g
        g.setdefault("_db_connections", []).append(connection)
        return connection

    # Standalone path — no pool, plain connection.
    try:
        return mysql.connector.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ.get("DB_NAME", "ERP"),
        )
    except KeyError as missing:
        logger.error(
            "Missing required database env var: %s. "
            "Copy .env.example to .env and fill in credentials.",
            missing,
        )
        return None
    except Error:
        logger.exception("Database connection failed")
        return None


def close_tracked_connections():
    """Return every connection leased during this request to the pool.

    Most routes call ``conn.close()`` themselves on the happy path, which
    already returns the pooled connection. This teardown is the safety net
    for routes that raised mid-execution. We swallow the ``PoolError``
    that mysql-connector raises when a connection is closed twice — it
    means the route already returned the slot, which is what we want.
    """
    from flask import g

    from mysql.connector.errors import PoolError

    for conn in g.pop("_db_connections", []):
        try:
            # For pooled connections, ``close()`` returns the underlying
            # socket to the pool rather than tearing it down.
            conn.close()
        except PoolError:
            # Already returned by the route's own conn.close(). Fine.
            pass
        except Exception:
            logger.exception("Error releasing pooled DB connection")
