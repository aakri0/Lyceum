"""Importing this package registers every @app.route handler.

Order doesn't matter — Flask doesn't care which module a route
lives in, only that the decorator has run by the time WSGI dispatch
starts. ``app.py`` imports this package at the bottom of the file.
"""

from . import admin, auth, faculty, misc, student  # noqa: F401
