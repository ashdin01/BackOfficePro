"""CRUD for bank reconciliation profiles and imported transactions."""
from database.connection import db_conn


# ── Profiles ──────────────────────────────────────────────────────────────────

def get_all_profiles():
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM bank_csv_profiles ORDER BY name COLLATE NOCASE"
        ).fetchall()]


def get_profile(profile_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM bank_csv_profiles WHERE id=?", (profile_id,)
        ).fetchone()
        return dict(row) if row else None


def save_profile(name, delimiter, has_header, skip_rows, date_format, amount_type,
                 col_date=None, col_amount=None, col_debit=None, col_credit=None,
                 col_description=None, col_reference=None, col_balance=None):
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM bank_csv_profiles WHERE name=?", (name,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE bank_csv_profiles SET
                    delimiter=?, has_header=?, skip_rows=?, date_format=?,
                    amount_type=?, col_date=?, col_amount=?, col_debit=?,
                    col_credit=?, col_description=?, col_reference=?, col_balance=?,
                    updated_at=datetime('now','localtime')
                WHERE name=?
            """, (delimiter, has_header, skip_rows, date_format, amount_type,
                  col_date, col_amount, col_debit, col_credit,
                  col_description, col_reference, col_balance, name))
            pid = existing['id']
        else:
            conn.execute("""
                INSERT INTO bank_csv_profiles
                    (name, delimiter, has_header, skip_rows, date_format,
                     amount_type, col_date, col_amount, col_debit, col_credit,
                     col_description, col_reference, col_balance)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (name, delimiter, has_header, skip_rows, date_format, amount_type,
                  col_date, col_amount, col_debit, col_credit,
                  col_description, col_reference, col_balance))
            pid = conn.execute(
                "SELECT id FROM bank_csv_profiles WHERE name=?", (name,)
            ).fetchone()['id']
        conn.commit()
        return pid


def delete_profile(profile_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM bank_csv_profiles WHERE id=?", (profile_id,))
        conn.commit()


# ── Transactions ──────────────────────────────────────────────────────────────

def insert_transactions(profile_id, batch, rows):
    with db_conn() as conn:
        for r in rows:
            conn.execute("""
                INSERT INTO bank_transactions
                    (profile_id, import_batch, txn_date, amount,
                     description, reference, balance)
                VALUES (?,?,?,?,?,?,?)
            """, (profile_id, batch,
                  r['txn_date'], r['amount'], r['description'],
                  r.get('reference') or '', r.get('balance')))
        conn.commit()


def get_transactions(batch):
    with db_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT * FROM bank_transactions
            WHERE import_batch=?
            ORDER BY txn_date, id
        """, (batch,)).fetchall()]


def get_all_batches():
    """Return summary of all import batches, newest first."""
    with db_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT import_batch,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='MATCHED'   THEN 1 ELSE 0 END) AS matched,
                   SUM(CASE WHEN status='UNMATCHED' THEN 1 ELSE 0 END) AS unmatched,
                   MIN(txn_date) AS date_from,
                   MAX(txn_date) AS date_to
            FROM bank_transactions
            GROUP BY import_batch
            ORDER BY import_batch DESC
        """).fetchall()]


def set_matched(txn_id, invoice_id, payment_id):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute(
            "SELECT status, invoice_id, payment_id FROM bank_transactions WHERE id=?",
            (txn_id,)
        ).fetchone()
        conn.execute("""
            UPDATE bank_transactions
            SET status='MATCHED', invoice_id=?, payment_id=?
            WHERE id=?
        """, (invoice_id, payment_id, txn_id))
        if old:
            record_changes(conn, 'bank_transaction', str(txn_id),
                           {'status': old['status'], 'invoice_id': old['invoice_id'],
                            'payment_id': old['payment_id']},
                           {'status': 'MATCHED', 'invoice_id': invoice_id,
                            'payment_id': payment_id},
                           get_user())
        conn.commit()


def set_ignored(txn_id):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute(
            "SELECT status FROM bank_transactions WHERE id=?", (txn_id,)
        ).fetchone()
        conn.execute(
            "UPDATE bank_transactions SET status='IGNORED' WHERE id=?",
            (txn_id,)
        )
        if old:
            record_changes(conn, 'bank_transaction', str(txn_id),
                           {'status': old['status']}, {'status': 'IGNORED'}, get_user())
        conn.commit()


def unmatch_transaction(txn_id):
    """Delete the linked payment, reset the transaction to UNMATCHED, and
    recalculate the invoice balance — all in one atomic transaction."""
    from datetime import date
    from models.audit_log import record_changes
    from database.audit_context import get_user

    with db_conn() as conn:
        row = conn.execute(
            "SELECT status, invoice_id, payment_id FROM bank_transactions WHERE id=?",
            (txn_id,)
        ).fetchone()
        if not row:
            return
        invoice_id = row['invoice_id']
        payment_id = row['payment_id']

        conn.execute("""
            UPDATE bank_transactions
            SET status='UNMATCHED', invoice_id=NULL, payment_id=NULL
            WHERE id=?
        """, (txn_id,))
        record_changes(conn, 'bank_transaction', str(txn_id),
                       {'status': row['status'], 'invoice_id': invoice_id,
                        'payment_id': payment_id},
                       {'status': 'UNMATCHED', 'invoice_id': None, 'payment_id': None},
                       get_user())

        if payment_id:
            conn.execute("DELETE FROM ar_payments WHERE id=?", (payment_id,))

        if invoice_id:
            # Recompute from remaining payments (deleted payment already excluded
            # because the DELETE above runs in the same transaction).
            total_paid = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM ar_payments WHERE invoice_id=?",
                (invoice_id,)
            ).fetchone()[0]
            conn.execute(
                "UPDATE ar_invoices"
                " SET amount_paid=?, updated_at=datetime('now','localtime')"
                " WHERE id=?",
                (total_paid, invoice_id)
            )
            inv = conn.execute(
                "SELECT total, due_date FROM ar_invoices WHERE id=?",
                (invoice_id,)
            ).fetchone()
            if inv:
                overdue = date.today().isoformat() > inv['due_date']
                if total_paid <= 0:
                    new_status = 'OVERDUE' if overdue else 'SENT'
                elif total_paid < float(inv['total']):
                    new_status = 'PARTIAL'
                else:
                    new_status = 'PAID'
                conn.execute(
                    "UPDATE ar_invoices SET status=? WHERE id=?",
                    (new_status, invoice_id)
                )

        conn.commit()
