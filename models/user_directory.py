"""
Cross-store user directory.

Each store (config.settings.STORES) has its own SQLite database with its
own `users` table — usernames are only UNIQUE within one store's file.
These helpers open short-lived direct connections to every store's database
to build a merged view, used for the combined sign-in screen and for
catching cross-store username collisions before they become ambiguous.

Deliberately does NOT use database.connection.db_conn() — that helper is
pinned to whichever single store is "active" for the rest of the app, but
this module needs to look at every store's file at once.
"""
import logging
import os
import sqlite3

import config.settings as _cfg


def _connect(db_path: str):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def list_all_active_users() -> list[dict]:
    """Return active users from every configured store, each tagged with
    the store they belong to."""
    users = []
    for store in _cfg.STORES:
        db_path = os.path.join(_cfg.DATA_DIR, store['db'])
        if not os.path.isfile(db_path):
            # Store DB not yet created (e.g. first run) — nothing to list.
            continue
        try:
            conn = _connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT id, username, full_name, role FROM users WHERE active=1 ORDER BY full_name"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            logging.warning("user_directory: could not read users from %s", db_path, exc_info=True)
            continue

        for row in rows:
            user = dict(row)
            user['store_name'] = store['name']
            user['db_path'] = db_path
            users.append(user)
    return users


def find_username_conflicts() -> list[str]:
    """Usernames that appear as active users in more than one store."""
    seen: dict[str, set] = {}
    for user in list_all_active_users():
        seen.setdefault(user['username'], set()).add(user['store_name'])
    return sorted(u for u, stores in seen.items() if len(stores) > 1)


def find_user_for_login(username: str) -> dict | None:
    """Look up a typed username across every store's active users.

    Returns the matching user dict (tagged with store_name/db_path) or None.
    Username matching is exact against the stored (lowercase) value — callers
    should normalise input the same way usernames are normalised at creation
    (see views/settings/settings_users.py:_UserDialog._validate).
    """
    for user in list_all_active_users():
        if user['username'] == username:
            return user
    return None


def find_other_store_conflict(username: str, exclude_db_path: str | None = None) -> str | None:
    """If `username` is already an active user in some other store, return
    that store's name. Used to block creating/renaming a user into a
    cross-store collision."""
    for user in list_all_active_users():
        if user['username'] == username and user['db_path'] != exclude_db_path:
            return user['store_name']
    return None
