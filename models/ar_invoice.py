"""CRUD operations for ar_invoices and ar_invoice_lines."""
from database.connection import get_connection


# ── Invoices ──────────────────────────────────────────────────────────────────

def get_all(customer_id=None, status=None):
    conn = get_connection()
    try:
        clauses, params = [], []
        if customer_id:
            clauses.append("i.customer_id = ?")
            params.append(customer_id)
        if status:
            clauses.append("i.status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return conn.execute(f"""
            SELECT i.*, c.name AS customer_name
            FROM ar_invoices i
            JOIN customers c ON c.id = i.customer_id
            {where}
            ORDER BY i.invoice_date DESC, i.invoice_number DESC
        """, params).fetchall()
    finally:
        conn.close()


def get_by_id(invoice_id):
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT i.*, c.name AS customer_name, c.abn AS customer_abn,
                   c.address_line1, c.address_line2, c.suburb, c.state,
                   c.postcode, c.email AS customer_email, c.payment_terms_days
            FROM ar_invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.id = ?
        """, (invoice_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create(invoice_number, customer_id, invoice_date, due_date,
           notes='', created_by=''):
    conn = get_connection()
    try:
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
    finally:
        conn.close()


def update_totals(invoice_id):
    """Recalculate subtotal, gst_amount, total from lines."""
    conn = get_connection()
    try:
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
        conn.commit()
    finally:
        conn.close()


def update_status(invoice_id, status):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE ar_invoices SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
            (status, invoice_id)
        )
        conn.commit()
    finally:
        conn.close()


def update_amount_paid(invoice_id, amount_paid):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE ar_invoices SET
                amount_paid=?, updated_at=datetime('now','localtime')
            WHERE id=?
        """, (amount_paid, invoice_id))
        conn.commit()
    finally:
        conn.close()


def update_notes(invoice_id, notes):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE ar_invoices SET notes=?, updated_at=datetime('now','localtime') WHERE id=?",
            (notes, invoice_id)
        )
        conn.commit()
    finally:
        conn.close()


def void_invoice(invoice_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE ar_invoices SET status='VOID', updated_at=datetime('now','localtime') WHERE id=?",
            (invoice_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ── Invoice lines ─────────────────────────────────────────────────────────────

def get_lines(invoice_id):
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM ar_invoice_lines WHERE invoice_id=? ORDER BY id",
            (invoice_id,)
        ).fetchall()]
    finally:
        conn.close()


def add_line(invoice_id, description, quantity, unit_price,
             discount_pct=0.0, gst_rate=10.0, barcode=''):
    subtotal, gst, total = _calc_line(quantity, unit_price, discount_pct, gst_rate)
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO ar_invoice_lines
                (invoice_id, barcode, description, quantity, unit_price,
                 discount_pct, gst_rate, line_subtotal, line_gst, line_total)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (invoice_id, barcode, description, quantity, unit_price,
              discount_pct, gst_rate, subtotal, gst, total))
        conn.commit()
    finally:
        conn.close()
    update_totals(invoice_id)


def update_line(line_id, description, quantity, unit_price,
                discount_pct=0.0, gst_rate=10.0, barcode=''):
    subtotal, gst, total = _calc_line(quantity, unit_price, discount_pct, gst_rate)
    conn = get_connection()
    try:
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
        conn.commit()
        invoice_id = inv_row['invoice_id'] if inv_row else None
    finally:
        conn.close()
    if invoice_id:
        update_totals(invoice_id)


def delete_line(line_id):
    conn = get_connection()
    try:
        inv_row = conn.execute(
            "SELECT invoice_id FROM ar_invoice_lines WHERE id=?", (line_id,)
        ).fetchone()
        conn.execute("DELETE FROM ar_invoice_lines WHERE id=?", (line_id,))
        conn.commit()
        invoice_id = inv_row['invoice_id'] if inv_row else None
    finally:
        conn.close()
    if invoice_id:
        update_totals(invoice_id)


def _calc_line(quantity, unit_price, discount_pct, gst_rate):
    discounted = unit_price * (1 - discount_pct / 100)
    subtotal   = round(quantity * discounted, 2)
    gst        = round(subtotal * gst_rate / 100, 2)
    total      = round(subtotal + gst, 2)
    return subtotal, gst, total
