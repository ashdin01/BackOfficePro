"""CRUD operations for ar_invoices and ar_invoice_lines."""
import sqlite3
import uuid

from database.connection import db_conn


# ── Invoices ──────────────────────────────────────────────────────────────────

def get_all(customer_id=None, status=None, limit=None, offset=0):
    with db_conn() as conn:
        clauses, params = [], []
        if customer_id:
            clauses.append("i.customer_id = ?")
            params.append(customer_id)
        if status:
            clauses.append("i.status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        return conn.execute(f"""
            SELECT i.*, c.name AS customer_name
            FROM ar_invoices i
            JOIN customers c ON c.id = i.customer_id
            {where}
            ORDER BY i.invoice_date DESC, i.invoice_number DESC
            {limit_clause}
        """, params).fetchall()


def count(customer_id=None, status=None) -> int:
    """Return the total number of invoices matching the given filters."""
    with db_conn() as conn:
        clauses, params = [], []
        if customer_id:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        row = conn.execute(
            f"SELECT COUNT(*) FROM ar_invoices {where}", params
        ).fetchone()
        return row[0] if row else 0


def get_by_id(invoice_id):
    with db_conn() as conn:
        row = conn.execute("""
            SELECT i.*, c.name AS customer_name, c.abn AS customer_abn,
                   c.address_line1, c.address_line2, c.suburb, c.state,
                   c.postcode, c.email AS customer_email, c.payment_terms_days
            FROM ar_invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.id = ?
        """, (invoice_id,)).fetchone()
        return dict(row) if row else None


def create(invoice_number, customer_id, invoice_date, due_date,
           notes='', created_by=''):
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO ar_invoices
                (invoice_number, customer_id, invoice_date, due_date,
                 status, notes, created_by)
            VALUES (?,?,?,?,'DRAFT',?,?)
        """, (invoice_number, customer_id, invoice_date, due_date,
              notes, created_by))
        conn.commit()
        return conn.execute(
            "SELECT id FROM ar_invoices WHERE invoice_number=?",
            (invoice_number,)
        ).fetchone()['id']


def _apply_totals(conn, invoice_id):
    """Recalculate invoice header totals using an already-open connection. Does NOT commit."""
    row = conn.execute("""
        SELECT COALESCE(SUM(line_subtotal), 0) AS subtotal,
               COALESCE(SUM(line_gst),      0) AS gst_amount,
               COALESCE(SUM(line_total),    0) AS total
        FROM ar_invoice_lines WHERE invoice_id = ?
    """, (invoice_id,)).fetchone()
    conn.execute("""
        UPDATE ar_invoices SET
            subtotal=?, gst_amount=?, total=?,
            updated_at=datetime('now','localtime')
        WHERE id=?
    """, (row['subtotal'], row['gst_amount'], row['total'], invoice_id))


def update_totals(invoice_id):
    """Recalculate subtotal, gst_amount, total from lines."""
    with db_conn() as conn:
        _apply_totals(conn, invoice_id)
        conn.commit()


_PAYMENT_STATUSES = {'PAID', 'PARTIAL'}


def update_status(invoice_id, status):
    if status in _PAYMENT_STATUSES:
        raise ValueError(
            f"Cannot set status '{status}' directly — use apply_payment() "
            "to keep amount_paid and status in sync."
        )
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute(
            "SELECT invoice_number, status FROM ar_invoices WHERE id=?", (invoice_id,)
        ).fetchone()
        conn.execute(
            "UPDATE ar_invoices SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
            (status, invoice_id)
        )
        if old:
            record_changes(conn, 'ar_invoice', old['invoice_number'],
                           {'status': old['status']}, {'status': status}, get_user())
        conn.commit()


def _update_amount_paid(invoice_id, amount_paid):
    """Internal helper — callers outside this module should use apply_payment()."""
    with db_conn() as conn:
        conn.execute("""
            UPDATE ar_invoices SET
                amount_paid=?, updated_at=datetime('now','localtime')
            WHERE id=?
        """, (amount_paid, invoice_id))
        conn.commit()


def update_notes(invoice_id, notes):
    with db_conn() as conn:
        conn.execute(
            "UPDATE ar_invoices SET notes=?, updated_at=datetime('now','localtime') WHERE id=?",
            (notes, invoice_id)
        )
        conn.commit()


def void_invoice(invoice_id):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute(
            "SELECT invoice_number, status FROM ar_invoices WHERE id=?", (invoice_id,)
        ).fetchone()
        conn.execute(
            "UPDATE ar_invoices SET status='VOID', updated_at=datetime('now','localtime') WHERE id=?",
            (invoice_id,)
        )
        if old:
            record_changes(conn, 'ar_invoice', old['invoice_number'],
                           {'status': old['status']}, {'status': 'VOID'}, get_user())
        conn.commit()


# ── Invoice lines ─────────────────────────────────────────────────────────────

def get_lines(invoice_id):
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM ar_invoice_lines WHERE invoice_id=? ORDER BY id",
            (invoice_id,)
        ).fetchall()]


def add_line(invoice_id, description, quantity, unit_price,
             discount_pct=0.0, gst_rate=10.0, barcode=''):
    subtotal, gst, total = _calc_line(quantity, unit_price, discount_pct, gst_rate)
    barcode = barcode or None
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO ar_invoice_lines
                (invoice_id, barcode, description, quantity, unit_price,
                 discount_pct, gst_rate, line_subtotal, line_gst, line_total)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (invoice_id, barcode, description, quantity, unit_price,
              discount_pct, gst_rate, subtotal, gst, total))
        _apply_totals(conn, invoice_id)
        conn.commit()


def update_line(line_id, description, quantity, unit_price,
                discount_pct=0.0, gst_rate=10.0, barcode=''):
    subtotal, gst, total = _calc_line(quantity, unit_price, discount_pct, gst_rate)
    barcode = barcode or None
    with db_conn() as conn:
        inv_row = conn.execute(
            "SELECT invoice_id FROM ar_invoice_lines WHERE id=?", (line_id,)
        ).fetchone()
        conn.execute("""
            UPDATE ar_invoice_lines SET
                barcode=?, description=?, quantity=?, unit_price=?,
                discount_pct=?, gst_rate=?,
                line_subtotal=?, line_gst=?, line_total=?
            WHERE id=?
        """, (barcode, description, quantity, unit_price,
              discount_pct, gst_rate, subtotal, gst, total, line_id))
        if inv_row:
            _apply_totals(conn, inv_row['invoice_id'])
        conn.commit()


def delete_line(line_id):
    with db_conn() as conn:
        inv_row = conn.execute(
            "SELECT invoice_id FROM ar_invoice_lines WHERE id=?", (line_id,)
        ).fetchone()
        conn.execute("DELETE FROM ar_invoice_lines WHERE id=?", (line_id,))
        if inv_row:
            _apply_totals(conn, inv_row['invoice_id'])
        conn.commit()


def get_unpaid_for_aged_debtors():
    """
    Return all non-paid invoice rows needed for aged debtors calculation.
    Each row: id, invoice_number, invoice_date, due_date, total, amount_paid,
              status, customer_id, customer_name, code.
    """
    with db_conn() as conn:
        return conn.execute("""
            SELECT i.id, i.invoice_number, i.invoice_date, i.due_date,
                   i.total, i.amount_paid, i.status,
                   c.id AS customer_id, c.name AS customer_name, c.code
            FROM ar_invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.status NOT IN ('PAID', 'VOID')
            ORDER BY c.name, i.due_date
        """).fetchall()


def refresh_overdue(today_str: str):
    """Mark SENT/PARTIAL invoices past due date as OVERDUE."""
    with db_conn() as conn:
        conn.execute("""
            UPDATE ar_invoices
            SET status='OVERDUE', updated_at=datetime('now','localtime')
            WHERE status IN ('SENT', 'PARTIAL')
              AND due_date < ?
        """, (today_str,))
        conn.commit()


def get_statement_rows(customer_id, date_from, date_to) -> dict:
    """
    Returns invoices and payments for a customer within a date range,
    plus opening balance (outstanding before date_from).
    Dict keys: opening_balance (float), invoices (list of dicts), payments (list of dicts).
    """
    with db_conn() as conn:
        opening_rows = conn.execute("""
            SELECT COALESCE(SUM(total - amount_paid), 0) AS balance
            FROM ar_invoices
            WHERE customer_id=? AND invoice_date < ? AND status NOT IN ('PAID','VOID')
        """, (customer_id, date_from)).fetchone()
        opening_balance = float(opening_rows['balance']) if opening_rows else 0.0

        invoices = [dict(r) for r in conn.execute("""
            SELECT invoice_number, invoice_date, due_date, total, amount_paid, status
            FROM ar_invoices
            WHERE customer_id=? AND invoice_date BETWEEN ? AND ?
              AND status != 'VOID'
            ORDER BY invoice_date
        """, (customer_id, date_from, date_to)).fetchall()]

        payments = [dict(r) for r in conn.execute("""
            SELECT p.payment_date, p.amount, p.method, p.reference,
                   i.invoice_number
            FROM ar_payments p
            JOIN ar_invoices i ON i.id = p.invoice_id
            WHERE p.customer_id=? AND p.payment_date BETWEEN ? AND ?
            ORDER BY p.payment_date
        """, (customer_id, date_from, date_to)).fetchall()]

        return {
            'opening_balance': opening_balance,
            'invoices':        invoices,
            'payments':        payments,
        }


def apply_payment(invoice_id, customer_id, payment_date, amount,
                  method='EFT', reference='', notes='',
                  payment_ref=None) -> tuple[int, float, str | None]:
    """
    Insert a payment row and update the invoice's amount_paid + status atomically.
    Returns (payment_id, total_paid, new_status).
    new_status is 'PAID', 'PARTIAL', or None (status unchanged when amount=0).

    payment_ref is a caller-supplied idempotency key.  If omitted a UUID is
    generated automatically.  A duplicate payment_ref means the call was already
    processed; the existing payment_id is returned immediately without touching
    the invoice again.
    """
    if payment_ref is None:
        payment_ref = str(uuid.uuid4())

    with db_conn() as conn:
        try:
            cur = conn.execute("""
                INSERT INTO ar_payments
                    (invoice_id, customer_id, payment_date, amount,
                     method, reference, notes, payment_ref)
                VALUES (?,?,?,?,?,?,?,?)
            """, (invoice_id, customer_id, payment_date, amount,
                  method, reference, notes, payment_ref))
            payment_id = cur.lastrowid
        except sqlite3.IntegrityError:
            conn.rollback()
            existing = conn.execute(
                "SELECT id FROM ar_payments WHERE payment_ref=?", (payment_ref,)
            ).fetchone()
            if existing:
                return existing['id'], 0.0, None
            raise

        # Single atomic statement: increment amount_paid by exactly the new
        # payment amount and recalculate status in one SQL round-trip.
        # Using amount_paid + ? (pre-update value) in the CASE expressions
        # avoids the SELECT-SUM race where two concurrent payments both read
        # a stale total before either has committed.
        upd = conn.execute("""
            UPDATE ar_invoices SET
                amount_paid = amount_paid + ?,
                status = CASE
                    WHEN amount_paid + ? >= total THEN 'PAID'
                    WHEN amount_paid + ? > 0      THEN 'PARTIAL'
                    ELSE status
                END,
                updated_at = datetime('now','localtime')
            WHERE id = ?
            RETURNING amount_paid, total
        """, (amount, amount, amount, invoice_id)).fetchone()

        total_paid = float(upd['amount_paid']) if upd else 0.0
        inv_total  = float(upd['total'])       if upd else 0.0

        if total_paid >= inv_total:
            new_status: str | None = 'PAID'
        elif total_paid > 0:
            new_status = 'PARTIAL'
        else:
            new_status = None

        conn.commit()
        return payment_id, total_paid, new_status


def _calc_line(quantity, unit_price, discount_pct, gst_rate):
    discounted = unit_price * (1 - discount_pct / 100)
    subtotal   = round(quantity * discounted, 2)
    gst        = round(subtotal * gst_rate / 100, 2)
    total      = round(subtotal + gst, 2)
    return subtotal, gst, total
