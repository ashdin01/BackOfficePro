from database.connection import get_connection


def get_all(active_only=True):
    conn = get_connection()
    if active_only:
        rows = conn.execute("SELECT * FROM departments WHERE active = 1 ORDER BY name").fetchall()
    else:
        rows = conn.execute("SELECT * FROM departments ORDER BY name").fetchall()
    conn.close()
    return rows


def get_by_id(dept_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM departments WHERE id = ?", (dept_id,)).fetchone()
    conn.close()
    return row


def add(code, name):
    conn = get_connection()
    conn.execute("INSERT INTO departments (code, name) VALUES (?, ?)", (code.upper(), name))
    conn.commit()
    conn.close()


def update(dept_id, code, name, active):
    conn = get_connection()
    conn.execute(
        "UPDATE departments SET code = ?, name = ?, active = ? WHERE id = ?",
        (code.upper(), name, active, dept_id)
    )
    conn.commit()
    conn.close()


def deactivate(dept_id):
    conn = get_connection()
    conn.execute("UPDATE departments SET active = 0 WHERE id = ?", (dept_id,))
    conn.commit()
    conn.close()
