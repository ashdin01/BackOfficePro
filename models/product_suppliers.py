from database.connection import get_connection


def get_by_barcode(barcode):
    """All supplier links for a product, default first."""
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT ps.supplier_id, s.name AS supplier_name, ps.is_default
            FROM product_suppliers ps
            JOIN suppliers s ON ps.supplier_id = s.id
            WHERE ps.barcode = ?
            ORDER BY ps.is_default DESC, s.name
        """, (barcode,)).fetchall()
    finally:
        conn.close()


def get_by_supplier(supplier_id, default_only=True):
    """All active products linked to a supplier."""
    conn = get_connection()
    try:
        sql = """
            SELECT p.*
            FROM products p
            JOIN product_suppliers ps ON ps.barcode = p.barcode
            WHERE ps.supplier_id = ? AND p.active = 1
        """
        if default_only:
            sql += " AND ps.is_default = 1"
        sql += " ORDER BY p.description"
        return conn.execute(sql, (supplier_id,)).fetchall()
    finally:
        conn.close()


def save_for_barcode(barcode, supplier_rows):
    """
    Replace all supplier links for a product in one transaction.
    supplier_rows: list of {'supplier_id': int, 'is_default': bool}
    Also keeps products.supplier_id in sync with the default.
    """
    conn = get_connection()
    try:
        conn.execute("DELETE FROM product_suppliers WHERE barcode = ?", (barcode,))
        default_id = None
        for row in supplier_rows:
            is_def = 1 if row['is_default'] else 0
            conn.execute(
                "INSERT INTO product_suppliers (barcode, supplier_id, is_default) VALUES (?, ?, ?)",
                (barcode, row['supplier_id'], is_def)
            )
            if row['is_default']:
                default_id = row['supplier_id']
        conn.execute(
            "UPDATE products SET supplier_id = ? WHERE barcode = ?",
            (default_id, barcode)
        )
        conn.commit()
    finally:
        conn.close()
