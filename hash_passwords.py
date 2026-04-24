"""
Utility to convert plaintext passwords in the `users` table to bcrypt hashes.

Usage:
    python hash_passwords.py

Reads DB credentials from the environment (see .env.example). Only rows whose
password does NOT already start with `$2b$` (bcrypt) are rehashed — existing
hashes are left untouched.
"""

from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from flask_bcrypt import Bcrypt

from db import get_connection


def main():
    app = Flask(__name__)
    bcrypt = Bcrypt(app)

    conn = get_connection()
    if conn is None:
        raise SystemExit("Could not connect to the database. Check your .env.")

    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT user_id, password FROM users")
    users = cur.fetchall()

    updated = 0
    for user in users:
        pwd = user["password"] or ""
        if pwd.startswith("$2b$"):
            continue

        hashed = bcrypt.generate_password_hash(pwd.strip()).decode()
        cur.execute(
            "UPDATE users SET password=%s WHERE user_id=%s",
            (hashed, user["user_id"]),
        )
        updated += 1
        print(f"Hashed password for user_id={user['user_id']}")

    conn.commit()
    conn.close()
    print(f"Done. {updated} password(s) hashed, {len(users) - updated} already bcrypt.")


if __name__ == "__main__":
    main()
