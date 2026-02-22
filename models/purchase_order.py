from database.connection import get_connection
from config.constants import PO_STATUS_DRAFT, PO_STATUS_CANCELLED


def _next_po_number(conn):
    row = conn.execute("SELECT value FROM settings WHERE key = 'po_next_number'").fetchone()
    prefix = conn.execute("SELECT value FROM settings WHERE key = 'po_prefix'").fetchone()
    number = int(row['value'])
    po_number = f"{prefix['value']}-{number:05d}"
    conn.execute("UPDATE settings SET value = ? WHERE key = 'po_next_number'", (number + 1,))
    return po_number


def get_all(status=None):
    conn = get_connection()
    query = """
        SELECT po.*, s.name as supplier_name
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
    """
    if status:
        query += " WHERE po.status = ?"
        rows = conn.execute(query + " ORDER BY po.created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute(query + " ORDER BY po.created_at DESC").fetchall()
    conn.close()
    return rows


def get_by_id(po_id):
    conn = get_connection()
    row = conn.execute("""
        SELECT po.*, s.name as supplier_name
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        WHERE po.id = ?
    """, (po_id,)).fetchone()
    conn.close()
    return row


def create(supplier_id, delivery_date=None, notes='', created_by=''):
    conn = get_connection()
    po_number = _next_po_number(conn)
    conn.execute("""
        INSERT INTO purchase_orders (po_number, supplier_id, delivery_date, notes, created_by)
        VALUES (?, ?, ?, ?, ?)
    """, (po_number, supplier_id, delivery_date, notes, created_by))
    conn.commit()
    po_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return po_id


def update_status(po_id, status):
    conn = get_connection()
    conn.execute("UPDATE purchase_orders SET status = ? WHERE id = ?", (status, po_id))
    conn.commit()
    conn.close()


def cancel(po_id):
    update_status(po_id, PO_STATUS_CANCELLED)
