from database.connection import get_connection


def save_charges(po_id: int, charges: list):
    """Replace all charges for a PO. charges = [{'description', 'tax_rate', 'amount_inc_tax'}]"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM po_charges WHERE po_id=?", (po_id,))
        for c in charges:
            conn.execute(
                "INSERT INTO po_charges (po_id, description, tax_rate, amount_inc_tax)"
                " VALUES (?,?,?,?)",
                (po_id, c['description'], c['tax_rate'], c['amount_inc_tax'])
            )
        conn.commit()
    finally:
        conn.close()


def get_by_po(po_id: int) -> list:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM po_charges WHERE po_id=? ORDER BY id", (po_id,)
        ).fetchall()]
    finally:
        conn.close()
