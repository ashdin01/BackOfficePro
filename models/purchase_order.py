from database.connection import get_connection
from config.constants import PO_STATUS_DRAFT, PO_STATUS_CANCELLED
from datetime import datetime, timedelta


def _next_po_number(conn):
    row    = conn.execute("SELECT value FROM settings WHERE key = 'po_next_number'").fetchone()
    prefix = conn.execute("SELECT value FROM settings WHERE key = 'po_prefix'").fetchone()
    number = int(row['value'])
    po_number = f"{prefix['value']}-{number:05d}"
    conn.execute("UPDATE settings SET value = ? WHERE key = 'po_next_number'", (number + 1,))
    return po_number


def get_all(status=None, archived=False):
    """
    archived=False → active POs (DRAFT, SENT, PARTIAL)
    archived=True  → archived POs (RECEIVED, CANCELLED that are kept)
    status=x       → filter by specific status (admin/filter use)
    """
    conn = get_connection()
    if status:
        query = """
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.status = ?
            ORDER BY po.created_at DESC
        """
        rows = conn.execute(query, (status,)).fetchall()
    elif archived:
        query = """
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.status IN ('RECEIVED', 'CANCELLED')
            ORDER BY po.created_at DESC
        """
        rows = conn.execute(query).fetchall()
    else:
        # Main screen — active only
        query = """
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.status IN ('DRAFT', 'SENT', 'PARTIAL')
            ORDER BY po.created_at DESC
        """
        rows = conn.execute(query).fetchall()
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
    conn.execute(
        "UPDATE purchase_orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, po_id)
    )
    conn.commit()
    conn.close()


def cancel(po_id):
    update_status(po_id, PO_STATUS_CANCELLED)


def cleanup_old_pos():
    """
    Run on startup:
    - Permanently delete CANCELLED POs older than 24 hours (+ their lines)
    Returns count of deleted POs.
    """
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        # Find old cancelled POs
        old = conn.execute("""
            SELECT id FROM purchase_orders
            WHERE status = 'CANCELLED'
            AND COALESCE(updated_at, created_at) < ?
        """, (cutoff,)).fetchall()

        count = len(old)
        for row in old:
            conn.execute("DELETE FROM po_lines WHERE po_id = ?", (row[0],))
            conn.execute("DELETE FROM purchase_orders WHERE id = ?", (row[0],))

        conn.commit()
        return count
    except Exception as e:
        print(f"PO cleanup error: {e}")
        return 0
    finally:
        conn.close()
