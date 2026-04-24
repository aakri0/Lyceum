import os

import mysql.connector
from mysql.connector import Error


def get_connection():
    """
    Open a new MySQL connection using env-based credentials.

    When called inside a Flask request, the connection is tracked on ``flask.g``
    so it will be closed automatically at teardown even if a route forgets to
    close it or raises mid-request. Standalone scripts (no app context) still
    get a plain connection and remain responsible for closing it.
    """
    try:
        connection = mysql.connector.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ.get("DB_NAME", "ERP"),
        )
    except KeyError as missing:
        print(f"❌ Missing required database env var: {missing}. "
              f"Copy .env.example to .env and fill in credentials.")
        return None
    except Error as e:
        print("❌ Database connection failed:", e)
        return None

    try:
        from flask import g, has_app_context

        if has_app_context():
            g.setdefault("_db_connections", []).append(connection)
    except Exception:
        # Flask not installed or not importable — fine for standalone scripts.
        pass

    return connection


def close_tracked_connections():
    """Close every connection registered on ``flask.g`` during this request."""
    from flask import g

    for conn in g.pop("_db_connections", []):
        try:
            if conn.is_connected():
                conn.close()
        except Exception:
            pass
