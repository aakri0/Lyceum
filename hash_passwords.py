from flask_bcrypt import Bcrypt
from db import get_connection
from flask import Flask

app = Flask(__name__)
bcrypt = Bcrypt(app)

conn = get_connection()
cur = conn.cursor(dictionary=True)

cur.execute("SELECT user_id, password FROM users")
users = cur.fetchall()

for user in users:
    pwd = user['password']

    # If already bcrypt, we must RESET (because old hash is wrong)
    if pwd.startswith('$2b$'):
        print(f"Resetting user {user['user_id']}")

        # ⚠️ YOU MUST KNOW THE ORIGINAL PASSWORD
        # TEMPORARY: set a known password
        clean_password = "test123"

        hashed = bcrypt.generate_password_hash(clean_password.strip()).decode()

        cur.execute(
            "UPDATE users SET password=%s WHERE user_id=%s",
            (hashed, user['user_id'])
        )

conn.commit()
conn.close()

print("✅ Passwords reset to 'test123'")
