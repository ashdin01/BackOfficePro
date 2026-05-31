from database.connection import db_conn


def get_all_settings():
    """Return all settings as a {key: value} dict."""
    with db_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r[0]: (r[1] or "") for r in rows}


def get_setting(key, default=''):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return (row[0] or default) if row else default


def set_setting(key, value):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        conn.commit()


def next_sequence(key, prefix) -> str:
    """
    Atomically increment a settings counter and return a formatted sequence number.
    e.g. next_sequence('ar_next_invoice_number', 'INV') → 'INV-00001'

    Uses UPDATE ... RETURNING so the read and increment are a single atomic SQL
    statement — safe across multiple OS processes (desktop GUI + Flask API) without
    any application-level lock.
    """
    with db_conn() as conn:
        row = conn.execute(
            "UPDATE settings SET value = CAST(value AS INTEGER) + 1"
            " WHERE key = ? RETURNING CAST(value AS INTEGER) - 1",
            (key,)
        ).fetchone()
        if row is None:
            # key absent: seed at 2 so next call returns 2, this call uses 1
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, '2')", (key,)
            )
            seq = 1
        else:
            seq = int(row[0])
        conn.commit()
        return f"{prefix}-{seq:05d}"
