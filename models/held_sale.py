from database.connection import db_conn


def _next_reference(conn) -> str:
    # Atomic UPDATE+RETURNING increments the counter and returns the old value
    # in one statement — safe when 3 POS terminals hit create-hold concurrently
    # against this same SQLite file. Mirrors purchase_order._next_po_number().
    prefix = conn.execute("SELECT value FROM settings WHERE key = 'hold_prefix'").fetchone()
    row    = conn.execute(
        "UPDATE settings SET value = CAST(value AS INTEGER) + 1"
        " WHERE key = 'hold_next_number' RETURNING CAST(value AS INTEGER) - 1",
    ).fetchone()
    number = int(row[0]) if row else 1
    return f"{prefix['value']}-{number:05d}"


def create(terminal_id, operator, items, *, subtotal, gst_amount, total, note='') -> dict:
    """
    Suspend a mid-transaction sale. items is a list of dicts:
        barcode, description, qty, unit_price, tax_rate, price_reason

    Does not touch stock_on_hand/sales_daily — those only change when the
    resumed sale is later completed through the existing /pos/sale flow.
    """
    with db_conn() as conn:
        reference = _next_reference(conn)
        cur = conn.execute("""
            INSERT INTO held_sales
                (reference, terminal_id, operator, note, subtotal, gst_amount, total, item_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (reference, terminal_id, operator, note, subtotal, gst_amount, total, len(items)))
        held_id = cur.lastrowid
        conn.executemany("""
            INSERT INTO held_sale_lines
                (held_sale_id, barcode, description, qty, unit_price, tax_rate, price_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            (held_id, i['barcode'], i['description'], i['qty'], i['unit_price'],
             i.get('tax_rate', 10.0), i.get('price_reason', ''))
            for i in items
        ])
        conn.commit()
        return {'id': held_id, 'reference': reference}


def get_open() -> list:
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM held_sales WHERE status='OPEN' ORDER BY created_at DESC"
        ).fetchall()]


def get_by_reference(reference) -> dict | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM held_sales WHERE reference=?", (reference,)
        ).fetchone()
        if not row:
            return None
        held = dict(row)
        held['lines'] = [dict(r) for r in conn.execute(
            "SELECT * FROM held_sale_lines WHERE held_sale_id=? ORDER BY id", (held['id'],)
        ).fetchall()]
        return held


def resume_atomic(reference, resumed_by_terminal) -> dict:
    """
    Atomically transition OPEN -> RESUMED and return the full basket.

    Raises LookupError if the reference doesn't exist, ValueError if it
    exists but isn't OPEN — checked inside this transaction (via BEGIN
    IMMEDIATE) so two terminals racing to resume the same hold can't both
    win (mirrors purchase_order.receive_atomic's status-guard pattern).
    """
    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM held_sales WHERE reference=?", (reference,)).fetchone()
        if not row:
            raise LookupError(f"Hold {reference} not found")
        if row['status'] != 'OPEN':
            raise ValueError(f"Hold {reference} cannot be resumed — status is '{row['status']}'")
        conn.execute("""
            UPDATE held_sales SET status='RESUMED',
                resumed_at=datetime('now','localtime'), resumed_by_terminal=?
            WHERE id=?
        """, (resumed_by_terminal, row['id']))
        lines = [dict(r) for r in conn.execute(
            "SELECT * FROM held_sale_lines WHERE held_sale_id=? ORDER BY id", (row['id'],)
        ).fetchall()]
        conn.commit()
        held = dict(row)
        held['status'] = 'RESUMED'
        held['lines'] = lines
        return held


def void(reference) -> None:
    """OPEN -> VOIDED. Raises LookupError if unknown, ValueError if not currently OPEN."""
    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM held_sales WHERE reference=?", (reference,)).fetchone()
        if not row:
            raise LookupError(f"Hold {reference} not found")
        if row['status'] != 'OPEN':
            raise ValueError(f"Hold {reference} cannot be voided — status is '{row['status']}'")
        conn.execute(
            "UPDATE held_sales SET status='VOIDED', voided_at=datetime('now','localtime') "
            "WHERE reference=?", (reference,)
        )
        conn.commit()
