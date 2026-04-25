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
        order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep=''):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO suppliers (
                code, name, contact_name, phone, account_number,
                payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
                email_orders, email_admin, email_accounts, email_rep
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
              email_orders, email_admin, email_accounts, email_rep))
        conn.commit()
    finally:
        conn.close()


def update(supplier_id, code, name, contact_name, phone, account_number,
           payment_terms, address, notes, active, abn='', rep_name='', rep_phone='',
           order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep=''):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE suppliers
            SET code=?, name=?, contact_name=?, phone=?,
                account_number=?, payment_terms=?, address=?, notes=?, active=?,
                abn=?, rep_name=?, rep_phone=?, order_minimum=?,
                email_orders=?, email_admin=?, email_accounts=?, email_rep=?
            WHERE id=?
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, active, abn, rep_name, rep_phone,
              order_minimum, email_orders, email_admin, email_accounts, email_rep,
              supplier_id))
        conn.commit()
    finally:
        conn.close()


def deactivate(supplier_id):
    conn = get_connection()
    try:
        conn.execute("UPDATE suppliers SET active = 0 WHERE id = ?", (supplier_id,))
        conn.commit()
    finally:
        conn.close()
