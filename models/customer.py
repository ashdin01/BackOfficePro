"""CRUD operations for the customers table."""
from database.connection import get_connection


def get_all(active_only=True):
    conn = get_connection()
    try:
        sql = "SELECT * FROM customers"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY name"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def get_by_id(customer_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_by_code(code):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE UPPER(code) = ?", (code.upper(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def add(code, name, abn='', address_line1='', address_line2='',
        suburb='', state='', postcode='', email='', phone='',
        contact_name='', payment_terms_days=37, credit_limit=0.0, notes=''):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO customers
                (code, name, abn, address_line1, address_line2,
                 suburb, state, postcode, email, phone,
                 contact_name, payment_terms_days, credit_limit, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (code.upper(), name, abn, address_line1, address_line2,
              suburb, state, postcode, email, phone,
              contact_name, payment_terms_days, credit_limit, notes))
        conn.commit()
    finally:
        conn.close()


def update(customer_id, code, name, abn='', address_line1='', address_line2='',
           suburb='', state='', postcode='', email='', phone='',
           contact_name='', payment_terms_days=37, credit_limit=0.0,
           active=1, notes=''):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE customers SET
                code=?, name=?, abn=?, address_line1=?, address_line2=?,
                suburb=?, state=?, postcode=?, email=?, phone=?,
                contact_name=?, payment_terms_days=?, credit_limit=?,
                active=?, notes=?, updated_at=datetime('now','localtime')
            WHERE id=?
        """, (code.upper(), name, abn, address_line1, address_line2,
              suburb, state, postcode, email, phone,
              contact_name, payment_terms_days, credit_limit,
              active, notes, customer_id))
        conn.commit()
    finally:
        conn.close()


def deactivate(customer_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE customers SET active=0, updated_at=datetime('now','localtime') WHERE id=?",
            (customer_id,)
        )
        conn.commit()
    finally:
        conn.close()
