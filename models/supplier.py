from database.connection import get_connection


def get_all(active_only=True):
    conn = get_connection()
    try:
        query = "SELECT * FROM suppliers"
        query += " WHERE active = 1" if active_only else ""
        query += " ORDER BY name"
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def get_by_id(supplier_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM suppliers WHERE id = ?", (supplier_id,)
        ).fetchone()
    finally:
        conn.close()


def add(code, name, contact_name='', phone='', account_number='',
        payment_terms='', address='', notes='', abn='', rep_name='', rep_phone='',
        order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep='',
        online_order=0, online_order_note='', order_days=''):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO suppliers (
                code, name, contact_name, phone, account_number,
                payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
                email_orders, email_admin, email_accounts, email_rep,
                online_order, online_order_note, order_days
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
              email_orders, email_admin, email_accounts, email_rep,
              online_order, online_order_note, order_days))
        conn.commit()
    finally:
        conn.close()


def update(supplier_id, code, name, contact_name, phone, account_number,
           payment_terms, address, notes, active, abn='', rep_name='', rep_phone='',
           order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep='',
           online_order=0, online_order_note='', order_days=''):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE suppliers
            SET code=?, name=?, contact_name=?, phone=?,
                account_number=?, payment_terms=?, address=?, notes=?, active=?,
                abn=?, rep_name=?, rep_phone=?, order_minimum=?,
                email_orders=?, email_admin=?, email_accounts=?, email_rep=?,
                online_order=?, online_order_note=?, order_days=?
            WHERE id=?
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, active, abn, rep_name, rep_phone,
              order_minimum, email_orders, email_admin, email_accounts, email_rep,
              online_order, online_order_note, order_days,
              supplier_id))
        conn.commit()
    finally:
        conn.close()


def get_order_due_today():
    """Return active suppliers whose order_days includes today's weekday,
    excluding any supplier that already has a SENT or CANCELLED PO updated today."""
    from datetime import date
    today = date.today().strftime('%a').upper()  # 'MON','TUE','WED','THU','FRI','SAT','SUN'
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM suppliers WHERE active=1 AND order_days != '' ORDER BY name"
        ).fetchall()
        due = [r for r in rows if today in (r['order_days'] or '').upper().split(',')]

        # Exclude suppliers with a SENT or CANCELLED PO updated today
        done_ids = {
            r[0] for r in conn.execute("""
                SELECT DISTINCT supplier_id FROM purchase_orders
                WHERE status IN ('SENT', 'CANCELLED')
                AND DATE(updated_at) = DATE('now')
            """).fetchall()
        }
        return [r for r in due if r['id'] not in done_ids]
    finally:
        conn.close()


def deactivate(supplier_id):
    conn = get_connection()
    try:
        conn.execute("UPDATE suppliers SET active = 0 WHERE id = ?", (supplier_id,))
        conn.commit()
    finally:
        conn.close()
