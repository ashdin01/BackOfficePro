import hashlib
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
    # Support both plain (legacy) and hashed PINs
    if stored == pin:
        # Migrate to hashed on first login
        set_pin(username, pin)
        return True
    return stored == _hash_pin(pin)


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
