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


def create(department_id, code, name):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO product_groups (department_id, code, name) VALUES (?, ?, ?)",
            (department_id, code.upper(), name)
        )
        conn.commit()


def update(group_id, department_id, code, name, active):
    with db_conn() as conn:
        conn.execute(
            "UPDATE product_groups SET department_id=?, code=?, name=?, active=? WHERE id=?",
            (department_id, code.upper(), name, active, group_id)
        )
        conn.commit()
