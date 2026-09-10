"""Model for stock_movements table."""
from database.connection import db_conn


def get_by_barcode(barcode, move_type=None):
    """
    Return stock movement rows for a product, newest first.
    Each row: (movement_type, quantity, reference, notes, created_at)
    Optionally filter by a specific movement_type string.
    """
    with db_conn() as conn:
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


def get_writeoff_qty_for_barcodes_range(barcodes, date_from, date_to, movement_type):
    """
    Bulk sum of write-off quantities (as positive units) for barcodes with the
    given movement_type, created between date_from and date_to (inclusive).
    Returns {barcode: float} — barcodes with no matching movements are omitted.
    """
    if not barcodes:
        return {}
    with db_conn() as conn:
        ph = ','.join('?' * len(barcodes))
        rows = conn.execute(f"""
            SELECT barcode, COALESCE(SUM(-quantity), 0) AS total
            FROM stock_movements
            WHERE barcode IN ({ph})
              AND movement_type = ?
              AND quantity < 0
              AND DATE(created_at) BETWEEN ? AND ?
            GROUP BY barcode
        """, barcodes + [movement_type, str(date_from), str(date_to)]).fetchall()
        return {r['barcode']: float(r['total']) for r in rows}


def get_recent_adjustments(limit=100):
    """
    Return the most recent non-sale/receipt stock movements across all products.
    Each row: (created_at, barcode, description, movement_type, quantity, reference, notes)
    """
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT m.created_at, m.barcode, p.description,
                   m.movement_type, m.quantity, m.reference, m.notes
            FROM stock_movements m
            LEFT JOIN products p ON m.barcode = p.barcode
            WHERE m.movement_type NOT IN ('SALE', 'RECEIPT')
            ORDER BY m.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [tuple(r) for r in rows]
