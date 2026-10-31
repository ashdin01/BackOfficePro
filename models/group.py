from database.connection import db_conn


def get_all(active_only=True):
    where = "WHERE g.active = 1" if active_only else ""
    with db_conn() as conn:
        return conn.execute(f"""
            SELECT g.*, d.name as dept_name, d.code as dept_code
            FROM product_groups g
            JOIN departments d ON g.department_id = d.id
            {where}
            ORDER BY d.name, g.name
        """).fetchall()


def get_by_department(department_id, active_only=True):
    where = "AND active = 1" if active_only else ""
    with db_conn() as conn:
        return conn.execute(f"""
            SELECT * FROM product_groups
            WHERE department_id = ?
            {where}
            ORDER BY name
        """, (department_id,)).fetchall()


def get_by_id(group_id):
    with db_conn() as conn:
        row = conn.execute("""
            SELECT g.*, d.name as dept_name
            FROM product_groups g
            JOIN departments d ON g.department_id = d.id
            WHERE g.id = ?
        """, (group_id,)).fetchone()
        return dict(row) if row else None


def create(department_id, code, name, track_use_by=False):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO product_groups (department_id, code, name, track_use_by) VALUES (?, ?, ?, ?)",
            (department_id, code.upper(), name, int(bool(track_use_by)))
        )
        conn.commit()


def update(group_id, department_id, code, name, active, track_use_by=None):
    """track_use_by=None leaves the flag unchanged."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE product_groups SET department_id=?, code=?, name=?, active=? WHERE id=?",
            (department_id, code.upper(), name, active, group_id)
        )
        if track_use_by is not None:
            conn.execute("UPDATE product_groups SET track_use_by=? WHERE id=?",
                         (int(bool(track_use_by)), group_id))
        conn.commit()


def set_track_use_by(group_id, track):
    with db_conn() as conn:
        conn.execute("UPDATE product_groups SET track_use_by=? WHERE id=?",
                     (int(bool(track)), group_id))
        conn.commit()


def tracks_use_by(group_id) -> bool:
    """True when products in this group need a use-by/best-before date on receipt."""
    if not group_id:
        return False
    with db_conn() as conn:
        row = conn.execute("SELECT track_use_by FROM product_groups WHERE id=?",
                           (group_id,)).fetchone()
        return bool(row and row['track_use_by'])
