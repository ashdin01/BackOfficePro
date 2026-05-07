import logging
from database.connection import get_connection
from config.constants import PO_STATUS_CANCELLED
from datetime import datetime, timedelta


def _next_po_number(conn):
    # The counter UPDATE and the PO INSERT share the same connection and are
    # committed together in create().  If the INSERT fails the whole transaction
    # rolls back, so the counter is never actually advanced — no gap occurs.
    row    = conn.execute("SELECT value FROM settings WHERE key = 'po_next_number'").fetchone()
    prefix = conn.execute("SELECT value FROM settings WHERE key = 'po_prefix'").fetchone()
    number = int(row['value'])
    po_number = f"{prefix['value']}-{number:05d}"
    conn.execute("UPDATE settings SET value = ? WHERE key = 'po_next_number'", (number + 1,))
    return po_number


def get_all(status=None, archived=False):
    """
    archived=False → active POs (DRAFT, SENT, PARTIAL)
    archived=True  → archived POs (RECEIVED, CANCELLED, REVERSED)
    status=x       → filter by specific status
    """
    conn = get_connection()
    try:
        if status:
            query = """
                SELECT po.*, s.name as supplier_name
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                WHERE po.status = ?
                ORDER BY po.created_at DESC
            """
            return conn.execute(query, (status,)).fetchall()
        elif archived:
            query = """
                SELECT po.*, s.name as supplier_name
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                WHERE po.status IN ('RECEIVED', 'CANCELLED', 'REVERSED')
                ORDER BY po.created_at DESC
            """
            return conn.execute(query).fetchall()
        else:
            query = """
                SELECT po.*, s.name as supplier_name
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                WHERE po.status IN ('DRAFT', 'SENT', 'PARTIAL')
                ORDER BY po.created_at DESC
            """
            return conn.execute(query).fetchall()
    finally:
        conn.close()


def get_by_id(po_id):
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.id = ?
        """, (po_id,)).fetchone()
    finally:
        conn.close()


def create(supplier_id, delivery_date=None, notes='', created_by=''):
    conn = get_connection()
    try:
        po_number = _next_po_number(conn)
        conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, delivery_date, notes, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (po_number, supplier_id, delivery_date, notes, created_by))
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def update_status(po_id, status):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE purchase_orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, po_id)
        )
        conn.commit()
    finally:
        conn.close()


def cancel(po_id):
    update_status(po_id, PO_STATUS_CANCELLED)


def reverse(po_id, reversed_by=''):
    """
    Reverse a RECEIVED or PARTIAL PO:
    - Reduces SOH for each received line
    - Records REVERSAL stock movements
    - Sets PO status to REVERSED
    """
    from models.stock_on_hand import adjust
    from config.constants import MOVE_REVERSAL

    conn = get_connection()
    try:
        po = conn.execute(
            "SELECT po.*, s.name as supplier_name FROM purchase_orders po "
            "JOIN suppliers s ON po.supplier_id = s.id WHERE po.id = ?",
            (po_id,)
        ).fetchone()
        if not po:
            raise ValueError(f'PO {po_id} not found')
        if po['status'] not in ('RECEIVED', 'PARTIAL'):
            raise ValueError('Only RECEIVED or PARTIAL POs can be reversed')
        lines = conn.execute(
            "SELECT * FROM po_lines WHERE po_id = ?", (po_id,)
        ).fetchall()
    finally:
        conn.close()

    for line in lines:
        received = int(line['received_qty'] or 0)
        if received <= 0:
            continue
        pack_qty = int(line['pack_qty']) if line['pack_qty'] else 1
        adjust(
            barcode=line['barcode'],
            quantity=-(received * pack_qty),
            movement_type=MOVE_REVERSAL,
            reference=po['po_number'],
            notes=f"Reversal of {po['po_number']} — {line['description']}",
            created_by=reversed_by,
        )

    update_status(po_id, 'REVERSED')


def cleanup_old_pos():
    """
    Delete CANCELLED POs older than 24 hours (and their lines).
    Returns count of deleted POs.
    """
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute("""
            DELETE FROM po_lines
            WHERE po_id IN (
                SELECT id FROM purchase_orders
                WHERE status = 'CANCELLED'
                AND COALESCE(updated_at, created_at) < ?
            )
        """, (cutoff,))
        cursor = conn.execute("""
            DELETE FROM purchase_orders
            WHERE status = 'CANCELLED'
            AND COALESCE(updated_at, created_at) < ?
        """, (cutoff,))
        count = cursor.rowcount
        conn.commit()
        return count
    except Exception as e:
        conn.rollback()
        logging.error(f"PO cleanup error: {e}", exc_info=True)
        return 0
    finally:
        conn.close()
