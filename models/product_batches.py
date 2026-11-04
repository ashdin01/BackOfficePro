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


def get_open_batches(barcode) -> list[dict]:
    """Unresolved batches for one product, soonest use-by first."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, use_by_date, qty_received FROM product_batches"
            " WHERE barcode = ? AND resolved = 0 ORDER BY use_by_date ASC, id ASC",
            (barcode,)).fetchall()
        return [dict(r) for r in rows]


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


def mark_resolved(batch_id, outcome=None, qty_remaining=None):
    """Dismiss a batch, optionally recording what happened to it.

    outcome: one of config.constants.BATCH_OUTCOMES codes (None = not captured).
    qty_remaining: units still on hand when it was handled (the waste/markdown qty).
    """
    with db_conn() as conn:
        conn.execute(
            "UPDATE product_batches SET resolved = 1, resolved_at = CURRENT_TIMESTAMP,"
            " outcome = ?, qty_remaining = ? WHERE id = ?",
            (outcome, qty_remaining, batch_id))
        conn.commit()
