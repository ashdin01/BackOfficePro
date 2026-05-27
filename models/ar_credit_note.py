"""Model for ar_credit_notes table."""
from database.connection import get_connection


def get_by_id(cn_id):
    """Return a credit note row as a dict, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM ar_credit_notes WHERE id=?", (cn_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


def create(credit_note_number, customer_id, invoice_id, cn_date, reason):
    """
    INSERT a new credit note row and return (id, credit_note_number).
    """
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO ar_credit_notes
                (credit_note_number, customer_id, invoice_id, date, reason)
            VALUES (?,?,?,?,?)
        """, (credit_note_number, customer_id, invoice_id, cn_date, reason))
        conn.commit()
        row = conn.execute(
            "SELECT id FROM ar_credit_notes WHERE credit_note_number=?",
            (credit_note_number,)
        ).fetchone()
        return row['id'], credit_note_number
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()
