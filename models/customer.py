"""CRUD operations for the customers table."""
from database.connection import get_connection


def get_all(active_only=True, limit=None, offset=0):
    conn = get_connection()
    try:
        params = []
        sql = "SELECT * FROM customers"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY name"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        return conn.execute(sql, params).fetchall()
    finally:
        conn.release()


def count(active_only=True) -> int:
    """Return the total number of customers matching the given filters."""
    conn = get_connection()
    try:
        sql = "SELECT COUNT(*) FROM customers"
        if active_only:
            sql += " WHERE active = 1"
        row = conn.execute(sql).fetchone()
        return row[0] if row else 0
    finally:
        conn.release()


def get_by_id(customer_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


def get_by_code(code):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE UPPER(code) = ?", (code.upper(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


def create(code, name, abn='', address_line1='', address_line2='',
        suburb='', state='', postcode='', email='', phone='',
        contact_name='', payment_terms_days=37, credit_limit=0.0,
        active=1, notes=''):
    conn = get_connection()
    try:
        cur = conn.execute("""
            INSERT INTO customers
                (code, name, abn, address_line1, address_line2,
                 suburb, state, postcode, email, phone,
                 contact_name, payment_terms_days, credit_limit, active, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (code.upper(), name, abn, address_line1, address_line2,
              suburb, state, postcode, email, phone,
              contact_name, payment_terms_days, credit_limit, active, notes))
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def update(customer_id, code, name, abn='', address_line1='', address_line2='',
           suburb='', state='', postcode='', email='', phone='',
           contact_name='', payment_terms_days=37, credit_limit=0.0,
           active=1, notes=''):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    conn = get_connection()
    try:
        old = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
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
        new = dict(code=code.upper(), name=name, abn=abn,
                   address_line1=address_line1, address_line2=address_line2,
                   suburb=suburb, state=state, postcode=postcode,
                   email=email, phone=phone, contact_name=contact_name,
                   payment_terms_days=payment_terms_days, credit_limit=credit_limit,
                   active=active, notes=notes)
        record_changes(conn, 'customer', code.upper(),
                       dict(old) if old else {}, new, get_user())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def deactivate(customer_id):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    conn = get_connection()
    try:
        old = conn.execute("SELECT code, active FROM customers WHERE id=?", (customer_id,)).fetchone()
        conn.execute(
            "UPDATE customers SET active=0, updated_at=datetime('now','localtime') WHERE id=?",
            (customer_id,)
        )
        key = old['code'] if old else str(customer_id)
        record_changes(conn, 'customer', key,
                       {'active': old['active']} if old else {},
                       {'active': 0}, get_user())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()
