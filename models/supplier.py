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

    Checks three schedule types:
    - Weekly: order_days contains today's weekday code ('MON', 'TUE', …)
    - First Monday: order_first_monday=1 and today is the first Monday of the month
    - Fortnightly: order_fortnightly_start is set and (today - start).days % 14 == 0
    Excludes any supplier with a SENT or CANCELLED PO updated today.
    """
    from datetime import date
    today = date.today()
    today_code = today.strftime('%a').upper()
    is_first_monday = (today.weekday() == 0 and today.day <= 7)

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM suppliers WHERE active=1 ORDER BY name"
        ).fetchall()

        due = []
        for r in rows:
            keys = r.keys()
            # Weekly days
            order_days = (r['order_days'] or '').upper()
            if order_days and today_code in order_days.split(','):
                due.append(r)
                continue
            # First Monday of the month
            if is_first_monday and 'order_first_monday' in keys and r['order_first_monday']:
                due.append(r)
                continue
            # Fortnightly from a fixed start date
            fn_start = r['order_fortnightly_start'] if 'order_fortnightly_start' in keys else ''
            if fn_start:
                try:
                    start = date.fromisoformat(fn_start)
                    delta = (today - start).days
                    if delta >= 0 and delta % 14 == 0:
                        due.append(r)
                        continue
                except ValueError:
                    pass

        # Suppress prompt if a DRAFT or SENT PO exists created/updated within the last 2 days
        done_ids = {
            r[0] for r in conn.execute("""
                SELECT DISTINCT supplier_id FROM purchase_orders
                WHERE status IN ('DRAFT', 'SENT')
                AND (
                    DATE(COALESCE(updated_at, created_at)) >= DATE('now', '-1 day')
                    OR DATE(created_at) >= DATE('now', '-1 day')
                )
            """).fetchall()
        }
        return [r for r in due if r['id'] not in done_ids]


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
