import hashlib
import hmac
from database.connection import get_connection


def _hash_pin(pin: str) -> str:
    """SHA-256 hash of a PIN string."""
    return hashlib.sha256(pin.encode()).hexdigest()


def get_all_active():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, full_name, role, pin FROM users WHERE active=1 ORDER BY full_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_by_username(username: str):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND active=1", (username,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def verify_pin(username: str, pin: str) -> bool:
    """Return True if PIN matches for this user."""
    user = get_by_username(username)
    if not user:
        return False
    stored = user.get('pin')
    if not stored:
        return False

    hashed = _hash_pin(pin)

    # Normal path: stored value is already a SHA-256 hash.
    if hmac.compare_digest(stored, hashed):
        return True

    # Legacy path: stored value is a plain-text PIN (pre-hash era).
    # Migrate to hashed on first successful login.
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
    finally:
        conn.close()


def create(username: str, full_name: str, role: str, pin: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) VALUES (?,?,?,?,1)",
            (username, full_name, role, _hash_pin(pin))
        )
        conn.commit()
    finally:
        conn.close()


def get_all():
    """Return all users including inactive, ordered by full_name."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, full_name, role, active FROM users ORDER BY full_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update(user_id: int, username: str, full_name: str, role: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET username=?, full_name=?, role=? WHERE id=?",
            (username, full_name, role, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_active(user_id: int, active: bool):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
        conn.commit()
    finally:
        conn.close()


def set_pin_by_id(user_id: int, pin: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET pin=? WHERE id=?", (_hash_pin(pin), user_id))
        conn.commit()
    finally:
        conn.close()


def has_any_pin_set() -> bool:
    """True if at least one active user has a PIN configured."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM users WHERE active=1 AND pin IS NOT NULL AND pin != ''"
        ).fetchone()
        return row[0] > 0
    finally:
        conn.close()
