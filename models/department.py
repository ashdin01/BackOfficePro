from database.connection import get_connection


def get_all(active_only=True):
    conn = get_connection()
    try:
        if active_only:
            return conn.execute("SELECT * FROM departments WHERE active = 1 ORDER BY name").fetchall()
        else:
            return conn.execute("SELECT * FROM departments ORDER BY name").fetchall()
    finally:
        conn.close()


def get_by_id(dept_id):
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM departments WHERE id = ?", (dept_id,)).fetchone()
    finally:
        conn.close()


def add(code, name):
    conn = get_connection()
    try:
        conn.execute("INSERT INTO departments (code, name) VALUES (?, ?)", (code.upper(), name))
        conn.commit()
    finally:
        conn.close()


def update(dept_id, code, name, active):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE departments SET code = ?, name = ?, active = ? WHERE id = ?",
            (code.upper(), name, active, dept_id)
        )
        conn.commit()
    finally:
        conn.close()


def deactivate(dept_id):
    conn = get_connection()
    try:
        conn.execute("UPDATE departments SET active = 0 WHERE id = ?", (dept_id,))
        conn.commit()
    finally:
        conn.close()
