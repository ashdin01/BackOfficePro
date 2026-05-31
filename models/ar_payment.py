"""CRUD operations for ar_payments."""
import uuid

from database.connection import db_conn


def get_by_invoice(invoice_id):
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM ar_payments WHERE invoice_id=? ORDER BY payment_date",
            (invoice_id,)
        ).fetchall()]


def get_by_customer(customer_id):
    with db_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT p.*, i.invoice_number
            FROM ar_payments p
            JOIN ar_invoices i ON i.id = p.invoice_id
            WHERE p.customer_id=?
            ORDER BY p.payment_date DESC
        """, (customer_id,)).fetchall()]


def create(invoice_id, customer_id, payment_date, amount,
        method='EFT', reference='', notes='', payment_ref=None):
    if payment_ref is None:
        payment_ref = str(uuid.uuid4())
    with db_conn() as conn:
        cur = conn.execute("""
            INSERT INTO ar_payments
                (invoice_id, customer_id, payment_date, amount,
                 method, reference, notes, payment_ref)
            VALUES (?,?,?,?,?,?,?,?)
        """, (invoice_id, customer_id, payment_date, amount,
              method, reference, notes, payment_ref))
        conn.commit()
        return cur.lastrowid


def total_paid(invoice_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM ar_payments WHERE invoice_id=?",
            (invoice_id,)
        ).fetchone()
        return float(row['total']) if row else 0.0
