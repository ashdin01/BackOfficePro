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
        online_order=0, online_order_note='', order_days='',
        order_first_monday=0, order_fortnightly_start=''):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO suppliers (
                code, name, contact_name, phone, account_number,
                payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
                email_orders, email_admin, email_accounts, email_rep,
                online_order, online_order_note, order_days,
                order_first_monday, order_fortnightly_start
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, abn, rep_name, rep_phone, order_minimum,
              email_orders, email_admin, email_accounts, email_rep,
              online_order, online_order_note, order_days,
              order_first_monday, order_fortnightly_start))
        conn.commit()
    finally:
        conn.close()


def update(supplier_id, code, name, contact_name, phone, account_number,
           payment_terms, address, notes, active, abn='', rep_name='', rep_phone='',
           order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep='',
           online_order=0, online_order_note='', order_days='',
           order_first_monday=0, order_fortnightly_start=''):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE suppliers
            SET code=?, name=?, contact_name=?, phone=?,
                account_number=?, payment_terms=?, address=?, notes=?, active=?,
                abn=?, rep_name=?, rep_phone=?, order_minimum=?,
                email_orders=?, email_admin=?, email_accounts=?, email_rep=?,
                online_order=?, online_order_note=?, order_days=?,
                order_first_monday=?, order_fortnightly_start=?
            WHERE id=?
        """, (code.upper(), name, contact_name, phone, account_number,
              payment_terms, address, notes, active, abn, rep_name, rep_phone,
              order_minimum, email_orders, email_admin, email_accounts, email_rep,
              online_order, online_order_note, order_days,
              order_first_monday, order_fortnightly_start,
              supplier_id))
        conn.commit()
    finally:
        conn.close()


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

    conn = get_connection()
    try:
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
    finally:
        conn.close()


def deactivate(supplier_id):
    conn = get_connection()
    try:
        conn.execute("UPDATE suppliers SET active = 0 WHERE id = ?", (supplier_id,))
        conn.commit()
    finally:
        conn.close()
