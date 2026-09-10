from datetime import date

from database.connection import db_conn


def add_batch(barcode, use_by_date, qty_received, po_line_id=None, received_date=None) -> int:
    """Record a received batch with its use-by/best-before date.

    Alerting-only: does not touch stock_on_hand — see product_batches
    table docstring in database/migrations.py (migrate_v69) for why.
    """
    received_date = received_date or date.today().isoformat()
    with db_conn() as conn:
        cur = conn.execute("""
            INSERT INTO product_batches
                (barcode, po_line_id, received_date, use_by_date, qty_received)
            VALUES (?, ?, ?, ?, ?)
        """, (barcode, po_line_id, received_date, use_by_date, qty_received))
        conn.commit()
        return cur.lastrowid


def get_expiring_batches(days: int = None) -> list[dict]:
    """Return unresolved batches whose use_by_date is within `days` (defaults
    to BATCH_EXPIRY_WARNING_DAYS), including any already past due.
    Ordered soonest-due first."""
    if days is None:
        from config.constants import BATCH_EXPIRY_WARNING_DAYS
        days = BATCH_EXPIRY_WARNING_DAYS
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT b.id, b.barcode, b.received_date, b.use_by_date, b.qty_received,
                   p.description
            FROM product_batches b
            JOIN products p ON p.barcode = b.barcode
            WHERE b.resolved = 0
              AND b.use_by_date <= date('now', '+' || ? || ' days')
            ORDER BY b.use_by_date ASC
        """, (days,)).fetchall()
        return [dict(r) for r in rows]


def mark_resolved(batch_id):
    with db_conn() as conn:
        conn.execute("UPDATE product_batches SET resolved = 1 WHERE id = ?", (batch_id,))
        conn.commit()
