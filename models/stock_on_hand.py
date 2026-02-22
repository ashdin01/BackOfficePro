from database.connection import get_connection


def get_by_barcode(barcode):
    conn = get_connection()
    row = conn.execute("SELECT * FROM stock_on_hand WHERE barcode = ?", (barcode,)).fetchone()
    conn.close()
    return row


def get_all_with_product():
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.*, p.description, p.reorder_point, p.reorder_qty, d.name as dept_name
        FROM stock_on_hand s
        JOIN products p     ON s.barcode = p.barcode
        JOIN departments d  ON p.department_id = d.id
        WHERE p.active = 1
        ORDER BY d.name, p.description
    """).fetchall()
    conn.close()
    return rows


def get_below_reorder():
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.barcode, p.description, s.quantity, p.reorder_point, p.reorder_qty,
               sup.name as supplier_name, d.name as dept_name
        FROM stock_on_hand s
        JOIN products p     ON s.barcode = p.barcode
        JOIN departments d  ON p.department_id = d.id
        LEFT JOIN suppliers sup ON p.supplier_id = sup.id
        WHERE s.quantity <= p.reorder_point AND p.active = 1
        ORDER BY p.description
    """).fetchall()
    conn.close()
    return rows


def adjust(barcode, quantity, movement_type, reference='', notes='', created_by=''):
    conn = get_connection()
    # Upsert stock on hand
    conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity)
        VALUES (?, ?)
        ON CONFLICT(barcode) DO UPDATE SET
            quantity = quantity + excluded.quantity,
            last_updated = CURRENT_TIMESTAMP
    """, (barcode, quantity))
    # Log movement
    conn.execute("""
        INSERT INTO stock_movements (barcode, movement_type, quantity, reference, notes, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (barcode, movement_type, quantity, reference, notes, created_by))
    conn.commit()
    conn.close()
