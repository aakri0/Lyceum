"""
One-off migration: add the `current_semester` column to the `students` table.

Usage:
    python migrate_semester.py

Safe to re-run — checks INFORMATION_SCHEMA before altering.
"""

import os

from dotenv import load_dotenv

load_dotenv()

from db import get_connection


def column_exists(cur, db_name, table, column):
    cur.execute(
        """
        SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (db_name, table, column),
    )
    return cur.fetchone()[0] > 0


def migrate():
    conn = get_connection()
    if conn is None:
        raise SystemExit("Could not connect to the database. Check your .env.")

    cur = conn.cursor()
    db_name = os.environ.get("DB_NAME", "ERP")

    try:
        if column_exists(cur, db_name, "students", "current_semester"):
            print("current_semester already exists on students — nothing to do.")
            return

        print("Altering students table...")
        cur.execute(
            "ALTER TABLE students ADD COLUMN current_semester INT DEFAULT 1"
        )
        conn.commit()
        print("Success: added current_semester column.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
