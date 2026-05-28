import hashlib
import hmac
import os
from database.connection import get_connection

_PBKDF2_ITERS  = 260_000
_PBKDF2_PREFIX = "pbkdf2:"


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
        return False


def get_all_active():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, full_name, role FROM users WHERE active=1 ORDER BY full_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()


def get_by_username(username: str):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND active=1", (username,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


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
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET pin=? WHERE username=?",
            (_hash_pin(pin), username)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def create(username: str, full_name: str, role: str, pin: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) VALUES (?,?,?,?,1)",
            (username, full_name, role, _hash_pin(pin))
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def get_all():
    """Return all users including inactive, ordered by full_name."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, full_name, role, active FROM users ORDER BY full_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()


def update(user_id: int, username: str, full_name: str, role: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET username=?, full_name=?, role=? WHERE id=?",
            (username, full_name, role, user_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def set_active(user_id: int, active: bool):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def set_pin_by_id(user_id: int, pin: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET pin=? WHERE id=?", (_hash_pin(pin), user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def has_any_pin_set() -> bool:
    """True if at least one active user has a PIN configured."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM users WHERE active=1 AND pin IS NOT NULL AND pin != ''"
        ).fetchone()
        return row[0] > 0
    finally:
        conn.release()
