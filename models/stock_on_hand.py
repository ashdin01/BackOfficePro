import sqlite3
from datetime import datetime

from config.constants import MOVE_ADJUSTMENT_IN, MOVE_RETURN
from database.connection import db_conn


def clamp_negative_soh(conn, barcode, reference='', created_by=''):
    """Reset a negative SOH to zero for products whose department has
    no_negative_soh set (e.g. Fresh — counts drift, so negative SOH is noise).

    Records a compensating ADJUSTMENT_IN movement for the clamped amount so
    movement-based reports still reconcile with the stored SOH.

    Must run inside the caller's transaction, after the SOH write and before
    commit. Returns the clamped quantity (0.0 if nothing was clamped).
    """
    row = conn.execute("""
        SELECT s.quantity
        FROM stock_on_hand s
        JOIN products p    ON p.barcode = s.barcode
        JOIN departments d ON d.id = p.department_id
        WHERE s.barcode = ? AND s.quantity < 0 AND d.no_negative_soh = 1
    """, (barcode,)).fetchone()
    if not row:
        return 0.0

    shortfall = -row['quantity']
    conn.execute(
        "UPDATE stock_on_hand SET quantity = 0, last_updated = CURRENT_TIMESTAMP"
        " WHERE barcode = ?",
        (barcode,)
    )
    from database.audit_context import get_user, get_source
    conn.execute("""
        INSERT INTO stock_movements
            (barcode, movement_type, quantity, reference, notes, created_by, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (barcode, MOVE_ADJUSTMENT_IN, shortfall, reference,
          'Auto-clamp: department does not allow negative SOH',
          created_by or get_user(), get_source()))
    return shortfall


def get_by_barcode(barcode):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM stock_on_hand WHERE barcode = ?", (barcode,)
        ).fetchone()
        return dict(row) if row else None


def get_all_with_product():
    with db_conn() as conn:
        return conn.execute("""
            SELECT s.*, p.description, p.reorder_point, p.reorder_qty, d.name as dept_name
            FROM stock_on_hand s
            JOIN products p     ON s.barcode = p.barcode
            JOIN departments d  ON p.department_id = d.id
            WHERE p.active = 1
            ORDER BY d.name, p.description
        """).fetchall()


def get_below_reorder():
    with db_conn() as conn:
        return conn.execute("""
            SELECT s.barcode, p.description, s.quantity, p.reorder_point, p.reorder_qty,
                   sup.name as supplier_name, d.name as dept_name
            FROM stock_on_hand s
            JOIN products p     ON s.barcode = p.barcode
            JOIN departments d  ON p.department_id = d.id
            LEFT JOIN suppliers sup ON p.supplier_id = sup.id
            WHERE s.quantity < p.reorder_point AND p.active = 1
            ORDER BY p.description
        """).fetchall()


def get_by_barcodes(barcodes):
    """Return a {barcode: quantity} map for a list of barcodes in a single query."""
    if not barcodes:
        return {}
    with db_conn() as conn:
        placeholders = ",".join("?" * len(barcodes))
        rows = conn.execute(
            f"SELECT barcode, quantity FROM stock_on_hand WHERE barcode IN ({placeholders})",
            barcodes
        ).fetchall()
        return {r["barcode"]: r["quantity"] for r in rows}


def adjust(barcode, quantity, movement_type, reference='', notes='', created_by=''):
    from database.audit_context import get_user, get_source
    who = created_by or get_user()
    src = get_source()
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO stock_on_hand (barcode, quantity)
            VALUES (?, ?)
            ON CONFLICT(barcode) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                last_updated = CURRENT_TIMESTAMP
        """, (barcode, quantity))
        conn.execute("""
            INSERT INTO stock_movements
                (barcode, movement_type, quantity, reference, notes, created_by, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (barcode, movement_type, quantity, reference, notes, who, src))
        clamp_negative_soh(conn, barcode, reference=reference, created_by=who)
        conn.commit()


def get_sale_header(reference: str):
    """Return the pos_sales ledger row for a receipt reference, or None."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pos_sales WHERE reference = ?", (reference,)
        ).fetchone()
        return dict(row) if row else None


def get_refund_header(reference: str):
    """Return the pos_refunds ledger row (including original_reference — the
    sale it refunds) for a refund reference, or None."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pos_refunds WHERE reference = ?", (reference,)
        ).fetchone()
        return dict(row) if row else None


def record_pos_sale_atomic(reference: str, sale_date: str, operator: str, items: list,
                            payment_method: str = '', subtotal: float | None = None,
                            gst_amount: float | None = None, total: float | None = None) -> bool:
    """
    Record a POS sale atomically.

    items: list of {barcode (alias-resolved), qty, line_total, description,
    unit_price, tax_rate}

    For each item, resolves selling-unit membership, reduces SOH, writes a
    SALE movement (with unit_price/line_total/tax_rate so the sale can later
    be viewed as a full receipt), looks up the PLU, and upserts into
    sales_daily. All writes share one connection and commit together.

    Returns True if the sale was newly recorded, False if this reference was
    already processed (idempotent — caller should respond 200, not 4xx/5xx).

    Raises ValueError if sale_date is not a valid YYYY-MM-DD date.
    """
    try:
        datetime.strptime(sale_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"sale_date must be YYYY-MM-DD, got: {sale_date!r}")

    from database.audit_context import get_source
    src = get_source()
    with db_conn() as conn:
        # Idempotency gate: claim the reference before touching stock.
        # If the POS retries after a network timeout, this INSERT fails and
        # we return False without touching SOH or movements a second time.
        try:
            conn.execute("""
                INSERT INTO pos_sales
                    (reference, sale_date, operator, payment_method, subtotal, gst_amount, total)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (reference, sale_date, operator, payment_method, subtotal, gst_amount, total))
        except sqlite3.IntegrityError:
            conn.rollback()
            return False

        for item in items:
            barcode     = item['barcode']
            qty         = float(item['qty'])
            line_total  = float(item['line_total'])
            description = item.get('description', '')
            unit_price  = item.get('unit_price')
            tax_rate    = item.get('tax_rate')

            if not barcode or qty <= 0:
                continue

            su = conn.execute(
                "SELECT master_barcode, unit_qty FROM product_selling_units "
                "WHERE barcode = ? AND active = 1",
                (barcode,)
            ).fetchone()
            if su:
                stock_barcode = su['master_barcode']
                stock_qty     = qty * (su['unit_qty'] or 1)
            else:
                stock_barcode = barcode
                stock_qty     = qty

            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (stock_barcode, -stock_qty))

            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source,
                     unit_price, line_total, tax_rate)
                VALUES (?, 'SALE', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (stock_barcode, -stock_qty, reference, description, operator, src,
                  unit_price, line_total, tax_rate))

            clamp_negative_soh(conn, stock_barcode, reference=reference, created_by=operator)

            plu_row = conn.execute(
                "SELECT plu FROM products WHERE barcode = ?", (stock_barcode,)
            ).fetchone()
            plu = (plu_row['plu'] or stock_barcode) if plu_row and plu_row['plu'] else stock_barcode

            conn.execute("""
                INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sale_date, plu) DO UPDATE SET
                    quantity      = quantity      + excluded.quantity,
                    sales_dollars = sales_dollars + excluded.sales_dollars
            """, (sale_date, plu, description, qty, line_total))

        conn.commit()
        return True


def record_pos_refund_atomic(refund_reference: str, original_reference: str, refund_date: str,
                              operator: str, lines: list,
                              subtotal: float | None = None,
                              gst_amount: float | None = None, total: float | None = None) -> bool:
    """
    Record a POS cash refund atomically — the reverse of record_pos_sale_atomic.

    lines: list of {barcode (alias-resolved), qty, line_total, description} — always
    positive numbers; the sign convention (negative qty/total for a refund) lives in
    RetailPOSPro's own local ledger, not this API.

    Never trusts the caller's own bookkeeping: for each line, validates against this
    sale's own stock_movements rows (what was actually sold, per BackOfficePro's own
    ledger) minus whatever pos_refund_lines already recorded as refunded against it —
    covering both a single over-refund and refunding the same line across several
    separate partial refunds. Raises ValueError if a line would over-refund, or if
    original_reference was never recorded as a sale.

    Returns True if newly recorded, False if refund_reference was already processed
    (idempotent — caller should respond 200, not 4xx/5xx).
    """
    try:
        datetime.strptime(refund_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"refund_date must be YYYY-MM-DD, got: {refund_date!r}")

    from database.audit_context import get_source
    src = get_source()
    with db_conn() as conn:
        sale = conn.execute(
            "SELECT reference FROM pos_sales WHERE reference=?", (original_reference,)
        ).fetchone()
        if not sale:
            raise ValueError(
                f"original_reference {original_reference!r} was never recorded as a sale"
            )

        # Idempotency gate: claim the reference before touching stock. If the
        # POS retries after a network timeout, this INSERT fails and we
        # return False without refunding stock a second time.
        try:
            conn.execute("""
                INSERT INTO pos_refunds
                    (reference, original_reference, refund_date, operator,
                     subtotal, gst_amount, total)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (refund_reference, original_reference, refund_date, operator,
                  subtotal, gst_amount, total))
        except sqlite3.IntegrityError:
            conn.rollback()
            return False
        refund_id = conn.execute(
            "SELECT id FROM pos_refunds WHERE reference=?", (refund_reference,)
        ).fetchone()['id']

        for item in lines:
            barcode     = item['barcode']
            qty         = float(item['qty'])
            line_total  = float(item['line_total'])
            description = item.get('description', '')

            if not barcode or qty <= 0:
                continue

            # Resolve to the stock barcode/unit qty FIRST — stock_movements
            # (written by record_pos_sale_atomic) always records the SALE
            # against the master barcode in master units, never the scanned
            # selling-unit barcode, so validation and pos_refund_lines must
            # both use the same resolved terms or a selling-unit refund would
            # never find its own sale.
            su = conn.execute(
                "SELECT master_barcode, unit_qty FROM product_selling_units "
                "WHERE barcode = ? AND active = 1",
                (barcode,)
            ).fetchone()
            if su:
                stock_barcode = su['master_barcode']
                stock_qty     = qty * (su['unit_qty'] or 1)
            else:
                stock_barcode = barcode
                stock_qty     = qty

            sold_row = conn.execute("""
                SELECT COALESCE(SUM(-quantity), 0) AS qty
                FROM stock_movements
                WHERE reference=? AND barcode=? AND movement_type='SALE'
            """, (original_reference, stock_barcode)).fetchone()
            sold_qty = sold_row['qty'] or 0.0

            refunded_row = conn.execute("""
                SELECT COALESCE(SUM(rl.qty), 0) AS qty
                FROM pos_refund_lines rl
                JOIN pos_refunds r ON r.id = rl.refund_id
                WHERE r.original_reference=? AND rl.barcode=?
            """, (original_reference, stock_barcode)).fetchone()
            already_refunded = refunded_row['qty'] or 0.0

            remaining = sold_qty - already_refunded
            if stock_qty > remaining + 1e-9:
                conn.rollback()
                raise ValueError(
                    f"Refund qty {stock_qty:g} for {stock_barcode} exceeds remaining "
                    f"refundable qty {remaining:g} (sold {sold_qty:g}, already refunded "
                    f"{already_refunded:g} on {original_reference})"
                )

            conn.execute("""
                INSERT INTO pos_refund_lines (refund_id, barcode, qty, line_total)
                VALUES (?, ?, ?, ?)
            """, (refund_id, stock_barcode, stock_qty, line_total))

            # Opposite sign to record_pos_sale_atomic's SALE write above:
            # stock increases, sales_daily decreases.
            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (stock_barcode, stock_qty))

            # notes holds the item description here, same convention as the SALE
            # write in record_pos_sale_atomic (views/products/transaction_history_dialog.py's
            # receipt renderer reads notes-or-description for the line's product name).
            # The link back to the original sale lives on pos_refunds.original_reference,
            # not repeated on every line.
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source,
                     unit_price, line_total, tax_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (stock_barcode, MOVE_RETURN, stock_qty, refund_reference,
                  description, operator, src,
                  None, line_total, None))

            plu_row = conn.execute(
                "SELECT plu FROM products WHERE barcode = ?", (stock_barcode,)
            ).fetchone()
            plu = (plu_row['plu'] or stock_barcode) if plu_row and plu_row['plu'] else stock_barcode

            conn.execute("""
                INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sale_date, plu) DO UPDATE SET
                    quantity      = quantity      + excluded.quantity,
                    sales_dollars = sales_dollars + excluded.sales_dollars
            """, (refund_date, plu, description, -qty, -line_total))

        conn.commit()
        return True
