from database.connection import db_conn


def get_all(active_only=True):
    with db_conn() as conn:
        query = "SELECT * FROM suppliers"
        query += " WHERE active = 1" if active_only else ""
        query += " ORDER BY name"
        return conn.execute(query).fetchall()


def get_by_id(supplier_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM suppliers WHERE id = ?", (supplier_id,)
        ).fetchone()


def create(code, name, contact_name='', phone='', account_number='',
        payment_terms='', address='', notes='', abn='', rep_name='', rep_phone='',
        order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep='',
        online_order=0, online_order_note='', order_days='',
        order_first_monday=0, order_fortnightly_start='', delivery_days='',
        bank_account_name='', bank_bsb='', bank_account_number=''):
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO suppliers (
                code, name, contact_name, phone, account_number,
                payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
                email_orders, email_admin, email_accounts, email_rep,
                online_order, online_order_note, order_days,
                order_first_monday, order_fortnightly_start, delivery_days,
                bank_account_name, bank_bsb, bank_account_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
              email_orders, email_admin, email_accounts, email_rep,
              online_order, online_order_note, order_days,
              order_first_monday, order_fortnightly_start, delivery_days,
              bank_account_name, bank_bsb, bank_account_number))
        conn.commit()


def update(supplier_id, code, name, contact_name, phone, account_number,
           payment_terms, address, notes, active, abn='', rep_name='', rep_phone='',
           order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep='',
           online_order=0, online_order_note='', order_days='',
           order_first_monday=0, order_fortnightly_start='', delivery_days='',
           bank_account_name='', bank_bsb='', bank_account_number=''):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        conn.execute("""
            UPDATE suppliers
            SET code=?, name=?, contact_name=?, phone=?,
                account_number=?, payment_terms=?, address=?, notes=?, active=?,
                abn=?, rep_name=?, rep_phone=?, order_minimum=?,
                email_orders=?, email_admin=?, email_accounts=?, email_rep=?,
                online_order=?, online_order_note=?, order_days=?,
                order_first_monday=?, order_fortnightly_start=?, delivery_days=?,
                bank_account_name=?, bank_bsb=?, bank_account_number=?
            WHERE id=?
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, active, abn, rep_name, rep_phone,
              order_minimum, email_orders, email_admin, email_accounts, email_rep,
              online_order, online_order_note, order_days,
              order_first_monday, order_fortnightly_start, delivery_days,
              bank_account_name, bank_bsb, bank_account_number,
              supplier_id))
        new = dict(code=code.upper(), name=name, contact_name=contact_name, phone=phone,
                   account_number=account_number, payment_terms=payment_terms,
                   address=address, notes=notes, active=active, abn=abn,
                   rep_name=rep_name, rep_phone=rep_phone, order_minimum=order_minimum,
                   email_orders=email_orders, email_admin=email_admin,
                   email_accounts=email_accounts, email_rep=email_rep,
                   online_order=online_order, online_order_note=online_order_note,
                   order_days=order_days, order_first_monday=order_first_monday,
                   order_fortnightly_start=order_fortnightly_start,
                   delivery_days=delivery_days, bank_account_name=bank_account_name,
                   bank_bsb=bank_bsb, bank_account_number=bank_account_number)
        record_changes(conn, 'supplier', name,
                       dict(old) if old else {}, new, get_user())
        conn.commit()


def get_order_due_today():
    """Return active suppliers with an order due today.

    Checks three schedule types in SQL:
    - Weekly: today's weekday code ('MON', 'TUE', …) appears in comma-separated order_days
    - First Monday: order_first_monday=1 and today is the first Monday of the month
    - Fortnightly: julianday distance from order_fortnightly_start is divisible by 14
    Excludes any supplier with a DRAFT/SENT PO created or updated within the last 2 days.
    """
    from datetime import date
    today = date.today()
    today_code    = today.strftime('%a').upper()          # 'MON', 'TUE', …
    is_first_monday = int(today.weekday() == 0 and today.day <= 7)

    with db_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM suppliers
            WHERE active = 1
              AND (
                -- Weekly: today's code appears in the comma-separated list
                ',' || UPPER(COALESCE(order_days, '')) || ',' LIKE '%,' || ? || ',%'
                -- First Monday of the month
                OR (? = 1 AND order_first_monday = 1)
                -- Fortnightly: whole number of 14-day periods since start date
                OR (
                    order_fortnightly_start IS NOT NULL
                    AND order_fortnightly_start != ''
                    AND CAST(julianday('now','localtime') - julianday(order_fortnightly_start)
                             AS INTEGER) >= 0
                    AND CAST(julianday('now','localtime') - julianday(order_fortnightly_start)
                             AS INTEGER) % 14 = 0
                )
              )
              -- Suppress if a DRAFT/SENT PO was created/updated in the last 2 days
              AND id NOT IN (
                SELECT DISTINCT supplier_id FROM purchase_orders
                WHERE status IN ('DRAFT', 'SENT')
                  AND DATE(COALESCE(updated_at, created_at)) >= DATE('now', '-1 day')
              )
            ORDER BY name
        """, (today_code, is_first_monday)).fetchall()
        return list(rows)


def deactivate(supplier_id):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute("SELECT name, active FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        conn.execute("UPDATE suppliers SET active = 0 WHERE id = ?", (supplier_id,))
        key = old['name'] if old else str(supplier_id)
        record_changes(conn, 'supplier', key,
                       {'active': old['active']} if old else {},
                       {'active': 0}, get_user())
        conn.commit()


def get_delivery_days(supplier_id) -> str | None:
    """Return the delivery_days string for a supplier, or None if not set / not found."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT delivery_days FROM suppliers WHERE id=?", (supplier_id,)
        ).fetchone()
        if not row:
            return None
        return (row['delivery_days'] or '').strip() or None
