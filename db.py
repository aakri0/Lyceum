"""MySQL connection factory backed by ``mysql-connector-python``'s pool.

Why a pool: every request opening a fresh TCP+TLS+auth handshake to MySQL
costs ~5-15ms on a healthy LAN and far more on a cold connection. With
a pool the request just leases an idle connection, so dashboards that
fire several short queries finish noticeably quicker, and the DB sees a
bounded connection count instead of one-per-concurrent-request.

Robustness model:
- The pool initialises *lazily* on first leased connection. We don't
  eagerly fill it at import time, because the DB may legitimately be
  down at app startup (e.g. docker-compose race, or running ``flask
  routes`` before MySQL boots). Failing eagerly would deadlock the
  whole app behind a None pool.
- If the pool itself can't be built (DB unreachable, wrong credentials)
  we fall back to a one-shot non-pooled connection — lets the request
  succeed if MySQL is up but pool construction had a transient miss.
- If both the pool *and* the non-pooled fallback fail, we raise
  ``DBUnavailable`` instead of returning None. The Flask error handler
  in ``app.py`` catches that and renders a friendly 503 page instead
  of an opaque ``AttributeError: 'NoneType' object has no attribute
  'cursor'`` from every route's first DB call.

Pool sizing: defaults to 10. mysql-connector caps the per-pool size at
32 — set ``DB_POOL_SIZE`` in env to override. Tune to roughly the
gunicorn worker count × concurrent-requests-per-worker, with a small
safety margin.

Standalone scripts (no Flask app context) bypass the pool entirely so a
one-shot script doesn't have to remember to call ``conn.close()``.
"""

from __future__ import annotations

import logging
import os
import threading

import mysql.connector
from mysql.connector import Error
from mysql.connector.pooling import MySQLConnectionPool

logger = logging.getLogger(__name__)


class DBUnavailable(Exception):
    """Raised when no DB connection can be obtained.

    The app's errorhandler turns this into a 503. Routes don't need to
    catch it — they can keep doing ``cur = conn.cursor()`` directly and
    rely on the framework to render a friendly page on failure.
    """


_POOL: MySQLConnectionPool | None = None
_POOL_LOCK = threading.Lock()


def _connect_kwargs() -> dict:
    """Read DB env once. Raises ``DBUnavailable`` if required vars missing."""
    try:
        return dict(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ.get("DB_NAME", "ERP"),
        )
    except KeyError as missing:
        raise DBUnavailable(
            f"Missing required database env var: {missing}. "
            f"Copy .env.example to .env and fill in credentials."
        ) from None


def _build_pool() -> MySQLConnectionPool | None:
    """Try to construct the singleton pool. None on transient failure."""
    try:
        return MySQLConnectionPool(
            pool_name="erp_pool",
            pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
            pool_reset_session=True,
            autocommit=False,
            **_connect_kwargs(),
        )
    except DBUnavailable:
        # Missing env vars — propagate so the caller surfaces it.
        raise
    except Error as e:
        logger.warning("Pool init failed (%s); will retry on next request.", e)
        return None


def _get_pool() -> MySQLConnectionPool | None:
    """Lazy singleton: try once per call until it sticks. Never caches None."""
    global _POOL
    if _POOL is not None:
        return _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = _build_pool()
    return _POOL


def _direct_connect():
    """One-shot non-pooled connection — used as the in-request fallback
    when the pool can't lease, and as the standalone-script default."""
    return mysql.connector.connect(**_connect_kwargs())


def get_connection():
    """Lease a MySQL connection.

    In-request: tries the pool, then falls back to a direct connection.
    Either way the connection is registered on ``flask.g`` and returned
    at teardown.

    Standalone (no app context): returns a plain non-pooled connection
    that the caller is responsible for closing.

    Raises ``DBUnavailable`` if neither path can produce a connection,
    so routes don't have to defensively check for None on every call.
    """
    try:
        from flask import g, has_app_context
        in_request = has_app_context()
    except Exception:
        in_request = False

    if in_request:
        # Path 1: the pool.
        pool = _get_pool()
        connection = None
        if pool is not None:
            try:
                connection = pool.get_connection()
            except Error as e:
                logger.warning("Pool lease failed (%s); falling back to direct connect.", e)

        # Path 2: direct connection fallback (also handles pool=None case).
        if connection is None:
            try:
                connection = _direct_connect()
            except Error as e:
                logger.exception("Direct DB connection failed")
                raise DBUnavailable(str(e)) from e

        from flask import g
        g.setdefault("_db_connections", []).append(connection)
        return connection

    # Standalone path — no pool, plain connection.
    try:
        return _direct_connect()
    except Error as e:
        logger.exception("Database connection failed")
        raise DBUnavailable(str(e)) from e


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
