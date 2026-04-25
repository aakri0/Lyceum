import os

import pytest

# Ensure required env vars are set BEFORE importing the app.
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("DB_NAME", "ERP_TEST")
os.environ.setdefault("EMAIL_ADDRESS", "test@example.com")
os.environ.setdefault("EMAIL_PASSWORD", "test-app-password")
# Force-https/HSTS off so tests use plain HTTP without 301 redirects.
os.environ.setdefault("SESSION_COOKIE_SECURE", "0")
# Lower bcrypt rounds so tests don't take forever.
os.environ.setdefault("BCRYPT_LOG_ROUNDS", "4")


@pytest.fixture
def app():
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
