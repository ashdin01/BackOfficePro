"""Audit log model — field-level change history for master data."""
from database.connection import get_connection

# Internal columns that are not meaningful to audit
_SKIP = frozenset({'id', 'created_at', 'updated_at'})


def _write(conn, entity: str, entity_key: str, field: str,
           old_value: str, new_value: str, changed_by: str) -> None:
    """Insert a single audit row on an already-open connection. Does NOT commit."""
    conn.execute("""
        INSERT INTO audit_log
            (entity, entity_key, field, old_value, new_value, changed_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (entity, entity_key, field, old_value, new_value, changed_by))


def record_changes(conn, entity: str, entity_key: str,
                   old_dict: dict, new_dict: dict, changed_by: str) -> None:
    """
    Compare old_dict and new_dict and write one audit row per changed field.
    Uses the caller's open connection — no commit is issued here.
    Fields in _SKIP are ignored.
    """
    for field, new_val in new_dict.items():
        if field in _SKIP:
            continue
        old_val = old_dict.get(field)
        old_str = '' if old_val is None else str(old_val)
        new_str = '' if new_val is None else str(new_val)
        if old_str != new_str:
            _write(conn, entity, entity_key, field, old_str, new_str, changed_by)


def get_for_entity(entity: str, entity_key: str, limit: int = 200) -> list[dict]:
    """Return audit rows for a specific record, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, entity, entity_key, field, old_value, new_value,
                   changed_by, changed_at
            FROM audit_log
            WHERE entity = ? AND entity_key = ?
            ORDER BY changed_at DESC, id DESC
            LIMIT ?
        """, (entity, entity_key, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()


def get_recent(limit: int = 200) -> list[dict]:
    """Return the most recent audit rows across all entities."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, entity, entity_key, field, old_value, new_value,
                   changed_by, changed_at
            FROM audit_log
            ORDER BY changed_at DESC, id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()
