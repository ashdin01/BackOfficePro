from database.connection import db_conn


def get_all(active_only=True):
    with db_conn() as conn:
        if active_only:
            return conn.execute("SELECT * FROM departments WHERE active = 1 ORDER BY name").fetchall()
        else:
            return conn.execute("SELECT * FROM departments ORDER BY name").fetchall()


def get_by_id(dept_id):
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM departments WHERE id = ?", (dept_id,)).fetchone()
        return dict(row) if row else None


def create(code, name, no_negative_soh=0):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO departments (code, name, no_negative_soh) VALUES (?, ?, ?)",
            (code.upper(), name, int(no_negative_soh))
        )
        conn.commit()


def update(dept_id, code, name, active, no_negative_soh=0):
    from models.audit_log import record_changes
    from database.audit_context import get_user, get_source
    with db_conn() as conn:
        old = conn.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone()
        conn.execute(
            "UPDATE departments SET code = ?, name = ?, active = ?, no_negative_soh = ? WHERE id = ?",
            (code.upper(), name, active, int(no_negative_soh), dept_id)
        )
        # When enabling the flag, immediately zero any existing negative SOH in
        # this department so the invariant holds without waiting for the next movement.
        flag_just_enabled = int(no_negative_soh) and not (old and old['no_negative_soh'])
        if flag_just_enabled:
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source)
                SELECT s.barcode, 'ADJUSTMENT_IN', -s.quantity,
                       'dept-flag', 'Auto-clamp: department does not allow negative SOH',
                       ?, ?
                FROM stock_on_hand s
                JOIN products p ON p.barcode = s.barcode
                WHERE p.department_id = ? AND s.quantity < 0
            """, (get_user(), get_source(), dept_id))
            conn.execute("""
                UPDATE stock_on_hand SET quantity = 0, last_updated = CURRENT_TIMESTAMP
                WHERE quantity < 0
                  AND barcode IN (SELECT barcode FROM products WHERE department_id = ?)
            """, (dept_id,))
        record_changes(conn, 'department', code.upper(),
                       dict(old) if old else {},
                       dict(code=code.upper(), name=name, active=active,
                            no_negative_soh=int(no_negative_soh)),
                       get_user())
        conn.commit()


def deactivate(dept_id):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute("SELECT code, active FROM departments WHERE id=?", (dept_id,)).fetchone()
        conn.execute("UPDATE departments SET active = 0 WHERE id = ?", (dept_id,))
        key = old['code'] if old else str(dept_id)
        record_changes(conn, 'department', key,
                       {'active': old['active']} if old else {},
                       {'active': 0}, get_user())
        conn.commit()
