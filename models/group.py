from database.connection import get_connection


def get_all(active_only=True):
    conn = get_connection()
    rows = conn.execute("""
        SELECT g.*, d.name as dept_name, d.code as dept_code
        FROM product_groups g
        JOIN departments d ON g.department_id = d.id
        {}
        ORDER BY d.name, g.name
    """.format("WHERE g.active = 1" if active_only else "")).fetchall()
    conn.close()
    return rows


def get_by_department(department_id, active_only=True):
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM product_groups
        WHERE department_id = ?
        {}
        ORDER BY name
    """.format("AND active = 1" if active_only else ""), (department_id,)).fetchall()
    conn.close()
    return rows


def get_by_id(group_id):
    conn = get_connection()
    row = conn.execute("""
        SELECT g.*, d.name as dept_name
        FROM product_groups g
        JOIN departments d ON g.department_id = d.id
        WHERE g.id = ?
    """, (group_id,)).fetchone()
    conn.close()
    return row


def add(department_id, code, name):
    conn = get_connection()
    conn.execute(
        "INSERT INTO product_groups (department_id, code, name) VALUES (?, ?, ?)",
        (department_id, code.upper(), name)
    )
    conn.commit()
    conn.close()


def update(group_id, department_id, code, name, active):
    conn = get_connection()
    conn.execute(
        "UPDATE product_groups SET department_id=?, code=?, name=?, active=? WHERE id=?",
        (department_id, code.upper(), name, active, group_id)
    )
    conn.commit()
    conn.close()
