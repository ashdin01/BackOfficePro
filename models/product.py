from database.connection import get_connection


def get_all(active_only=True):
    conn = get_connection()
    query = """
        SELECT p.*, d.name as dept_name, s.name as supplier_name
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        LEFT JOIN suppliers s   ON p.supplier_id   = s.id
    """
    query += " WHERE p.active = 1" if active_only else ""
    query += " ORDER BY p.description"
    rows = conn.execute(query).fetchall()
    conn.close()
    return rows


def get_by_barcode(barcode):
    conn = get_connection()
    row = conn.execute("""
        SELECT p.*, d.name as dept_name, s.name as supplier_name
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        LEFT JOIN suppliers s   ON p.supplier_id   = s.id
        WHERE p.barcode = ?
    """, (barcode,)).fetchone()
    conn.close()
    return row


def search(term):
    conn = get_connection()
    like = f"%{term}%"
    rows = conn.execute("""
        SELECT p.*, d.name as dept_name, s.name as supplier_name
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        LEFT JOIN suppliers s   ON p.supplier_id   = s.id
        WHERE (p.description LIKE ? OR p.barcode LIKE ?) AND p.active = 1
        ORDER BY p.description
    """, (like, like)).fetchall()
    conn.close()
    return rows


def add(barcode, description, department_id, supplier_id=None, unit='EA',
        sell_price=0, cost_price=0, tax_rate=0, reorder_point=0,
        reorder_qty=0, variable_weight=0, expected=1):
    conn = get_connection()
    conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id, unit,
             sell_price, cost_price, tax_rate, reorder_point, reorder_qty,
             variable_weight, expected)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (barcode, description, department_id, supplier_id, unit,
          sell_price, cost_price, tax_rate, reorder_point, reorder_qty,
          variable_weight, expected))
    conn.commit()
    conn.close()


def update(barcode, description, department_id, supplier_id, unit,
           sell_price, cost_price, tax_rate, reorder_point, reorder_qty,
           variable_weight, expected, active):
    conn = get_connection()
    conn.execute("""
        UPDATE products
        SET description=?, department_id=?, supplier_id=?, unit=?,
            sell_price=?, cost_price=?, tax_rate=?, reorder_point=?,
            reorder_qty=?, variable_weight=?, expected=?, active=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE barcode=?
    """, (description, department_id, supplier_id, unit, sell_price,
          cost_price, tax_rate, reorder_point, reorder_qty,
          variable_weight, expected, active, barcode))
    conn.commit()
    conn.close()


def deactivate(barcode):
    conn = get_connection()
    conn.execute("UPDATE products SET active = 0 WHERE barcode = ?", (barcode,))
    conn.commit()
    conn.close()
