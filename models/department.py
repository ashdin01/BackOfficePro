from database.connection import get_connection


def get_all(active_only=True):
    conn = get_connection()
    try:
        if active_only:
            return conn.execute("SELECT * FROM departments WHERE active = 1 ORDER BY name").fetchall()
        else:
            return conn.execute("SELECT * FROM departments ORDER BY name").fetchall()
    finally:
        conn.release()


def get_by_id(dept_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM departments WHERE id = ?", (dept_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


def create(code, name):
    conn = get_connection()
    try:
        conn.execute("INSERT INTO departments (code, name) VALUES (?, ?)", (code.upper(), name))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def update(dept_id, code, name, active):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    conn = get_connection()
    try:
        old = conn.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone()
        conn.execute(
            "UPDATE departments SET code = ?, name = ?, active = ? WHERE id = ?",
            (code.upper(), name, active, dept_id)
        )
        record_changes(conn, 'department', code.upper(),
                       dict(old) if old else {},
                       dict(code=code.upper(), name=name, active=active),
                       get_user())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def deactivate(dept_id):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    conn = get_connection()
    try:
        old = conn.execute("SELECT code, active FROM departments WHERE id=?", (dept_id,)).fetchone()
        conn.execute("UPDATE departments SET active = 0 WHERE id = ?", (dept_id,))
        key = old['code'] if old else str(dept_id)
        record_changes(conn, 'department', key,
                       {'active': old['active']} if old else {},
                       {'active': 0}, get_user())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()
