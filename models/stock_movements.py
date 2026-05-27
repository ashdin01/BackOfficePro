"""Model for stock_movements table."""
from database.connection import get_connection


def get_by_barcode(barcode, move_type=None):
    """
    Return stock movement rows for a product, newest first.
    Each row: (movement_type, quantity, reference, notes, created_at)
    Optionally filter by a specific movement_type string.
    """
    conn = get_connection()
    try:
        sql = """
            SELECT movement_type, quantity, reference, notes, created_at
            FROM stock_movements
            WHERE barcode = ?
        """
        params = [barcode]
        if move_type and move_type != "ALL":
            sql += " AND movement_type = ?"
            params.append(move_type)
        sql += " ORDER BY created_at DESC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.release()


def get_recent_adjustments(limit=100):
    """
    Return the most recent non-sale/receipt stock movements across all products.
    Each row: (created_at, barcode, description, movement_type, quantity, reference, notes)
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT m.created_at, m.barcode, p.description,
                   m.movement_type, m.quantity, m.reference, m.notes
            FROM stock_movements m
            LEFT JOIN products p ON m.barcode = p.barcode
            WHERE m.movement_type NOT IN ('SALE', 'RECEIPT')
            ORDER BY m.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [tuple(r) for r in rows]
    finally:
        conn.release()
