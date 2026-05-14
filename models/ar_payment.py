"""CRUD operations for ar_payments."""
from database.connection import get_connection


def get_by_invoice(invoice_id):
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM ar_payments WHERE invoice_id=? ORDER BY payment_date",
            (invoice_id,)
        ).fetchall()]
    finally:
        conn.close()


def get_by_customer(customer_id):
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT p.*, i.invoice_number
            FROM ar_payments p
            JOIN ar_invoices i ON i.id = p.invoice_id
            WHERE p.customer_id=?
            ORDER BY p.payment_date DESC
        """, (customer_id,)).fetchall()]
    finally:
        conn.close()


def add(invoice_id, customer_id, payment_date, amount,
        method='EFT', reference='', notes=''):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO ar_payments
                (invoice_id, customer_id, payment_date, amount,
                 method, reference, notes)
            VALUES (?,?,?,?,?,?,?)
        """, (invoice_id, customer_id, payment_date, amount,
              method, reference, notes))
        conn.commit()
    finally:
        conn.close()


def total_paid(invoice_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM ar_payments WHERE invoice_id=?",
            (invoice_id,)
        ).fetchone()
        return float(row['total']) if row else 0.0
    finally:
        conn.close()
