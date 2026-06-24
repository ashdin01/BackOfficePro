import hashlib
import hmac
import logging
import os
from database.connection import db_conn

_PBKDF2_ITERS  = 260_000
_PBKDF2_PREFIX = "pbkdf2:"
_PIN_MIN = 4
_PIN_MAX = 8


def _validate_pin(pin: str) -> None:
    """Raise ValueError if pin is not 4–8 digits."""
    if not isinstance(pin, str) or not pin.isdigit() or not (_PIN_MIN <= len(pin) <= _PIN_MAX):
        raise ValueError(f"PIN must be {_PIN_MIN}–{_PIN_MAX} digits")


def _hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2:{salt.hex()}:{dk.hex()}"


def _verify_pbkdf2(pin: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split(':')
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, _PBKDF2_ITERS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        logging.warning("_verify_pbkdf2: malformed stored hash — returning False", exc_info=True)
        return False


def get_all_active():
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, full_name, role FROM users WHERE active=1 ORDER BY full_name"
        ).fetchall()
        return [dict(r) for r in rows]


def get_by_username(username: str):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND active=1", (username,)
        ).fetchone()
        return dict(row) if row else None


def verify_pin(username: str, pin: str) -> bool:
    """Return True if PIN matches for this user."""
    user = get_by_username(username)
    if not user:
        return False
    stored = user.get('pin')
    if not stored:
        return False

    # Current path: PBKDF2-SHA256 with per-user salt.
    if stored.startswith(_PBKDF2_PREFIX):
        return _verify_pbkdf2(pin, stored)

    # Legacy: unsalted SHA-256 — auto-migrate to PBKDF2 on success.
    if hmac.compare_digest(stored, hashlib.sha256(pin.encode()).hexdigest()):
        set_pin(username, pin)
        return True

    # Legacy: plaintext PIN — auto-migrate to PBKDF2 on success.
    if hmac.compare_digest(stored, pin):
        set_pin(username, pin)
        return True

    return False


def set_pin(username: str, pin: str):
    _validate_pin(pin)
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET pin=? WHERE username=?",
            (_hash_pin(pin), username)
        )
        record_changes(conn, 'user', username,
                       {'pin': '[protected]'}, {'pin': '[changed]'}, get_user())
        conn.commit()


def _check_cross_store_conflict(username: str):
    """Raise ValueError if `username` is already active in another store.

    Usernames now double as the lookup key for the merged cross-store
    sign-in screen, so a collision would make login ambiguous.
    """
    import database.connection as _db_conn
    from models.user_directory import find_other_store_conflict
    conflict_store = find_other_store_conflict(username, exclude_db_path=_db_conn.DATABASE_PATH)
    if conflict_store:
        raise ValueError(
            f"Username '{username}' is already in use at {conflict_store}. "
            "Usernames must be unique across all stores."
        )


def create(username: str, full_name: str, role: str, pin: str):
    _validate_pin(pin)
    _check_cross_store_conflict(username)
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) VALUES (?,?,?,?,1)",
            (username, full_name, role, _hash_pin(pin))
        )
        record_changes(conn, 'user', username, {},
                       {'role': role, 'active': '1'}, get_user())
        conn.commit()


def get_all():
    """Return all users including inactive, ordered by full_name."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, full_name, role, active FROM users ORDER BY full_name"
        ).fetchall()
        return [dict(r) for r in rows]


def update(user_id: int, username: str, full_name: str, role: str):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute(
            "SELECT username, full_name, role FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not old or old['username'] != username:
            _check_cross_store_conflict(username)
        conn.execute(
            "UPDATE users SET username=?, full_name=?, role=? WHERE id=?",
            (username, full_name, role, user_id)
        )
        if old:
            record_changes(conn, 'user', username,
                           dict(old),
                           {'username': username, 'full_name': full_name, 'role': role},
                           get_user())
        conn.commit()


def set_active(user_id: int, active: bool):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    new_val = 1 if active else 0
    with db_conn() as conn:
        old = conn.execute(
            "SELECT username, active FROM users WHERE id=?", (user_id,)
        ).fetchone()
        conn.execute("UPDATE users SET active=? WHERE id=?", (new_val, user_id))
        if old:
            record_changes(conn, 'user', old['username'],
                           {'active': str(old['active'])},
                           {'active': str(new_val)},
                           get_user())
        conn.commit()


def set_pin_by_id(user_id: int, pin: str):
    _validate_pin(pin)
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        conn.execute("UPDATE users SET pin=? WHERE id=?", (_hash_pin(pin), user_id))
        if row:
            record_changes(conn, 'user', row['username'],
                           {'pin': '[protected]'}, {'pin': '[changed]'}, get_user())
        conn.commit()


def has_any_pin_set() -> bool:
    """True if at least one active user has a PIN configured."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM users WHERE active=1 AND pin IS NOT NULL AND pin != ''"
        ).fetchone()
        return row[0] > 0
