from database.connection import db_conn
from config.constants import PO_CHARGE_TYPE_OTHER


def save_charges(po_id: int, charges: list):
    """Replace all charges for a PO.

    charges = [{'description', 'tax_rate', 'amount_inc_tax', 'charge_type'}]
    charge_type defaults to OTHER when omitted.
    """
    with db_conn() as conn:
        conn.execute("DELETE FROM po_charges WHERE po_id=?", (po_id,))
        for c in charges:
            conn.execute(
                "INSERT INTO po_charges (po_id, charge_type, description, tax_rate, amount_inc_tax)"
                " VALUES (?,?,?,?,?)",
                (po_id, c.get('charge_type') or PO_CHARGE_TYPE_OTHER,
                 c['description'], c['tax_rate'], c['amount_inc_tax'])
            )
        conn.commit()


def get_by_po(po_id: int) -> list:
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM po_charges WHERE po_id=? ORDER BY id", (po_id,)
        ).fetchall()]
