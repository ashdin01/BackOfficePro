"""Model for product_selling_units table."""
from database.connection import db_conn


def get_master(barcode):
    """
    If barcode is an active selling unit, return a dict with master_barcode,
    master_desc, label, unit_qty. Returns None if it is not a selling unit.
    """
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT su.master_barcode, su.label, su.unit_qty,
                   p.description AS master_desc
            FROM product_selling_units su
            JOIN products p ON su.master_barcode = p.barcode
            WHERE su.barcode = ? AND su.active = 1
            """,
            (barcode,)
        ).fetchone()
        return dict(row) if row else None


def get_by_master(master_barcode):
    """All selling units for a product, ordered by unit_qty. Returns list of dicts."""
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, label, unit_qty, plu, barcode, sell_price "
            "FROM product_selling_units WHERE master_barcode=? ORDER BY unit_qty",
            (master_barcode,)
        ).fetchall()]


def get_by_id(su_id):
    """Single selling unit row as a dict, or None."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, label, unit_qty, plu, barcode, sell_price "
            "FROM product_selling_units WHERE id=?",
            (su_id,)
        ).fetchone()
        return dict(row) if row else None


def add(master_barcode, barcode, plu, label, unit_qty, sell_price):
    """Insert a new selling unit row."""
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO product_selling_units "
            "(master_barcode, barcode, plu, label, unit_qty, sell_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (master_barcode, barcode, plu, label, unit_qty, sell_price)
        )
        conn.commit()


def update(su_id, label, unit_qty, plu, barcode, sell_price):
    """Update label, qty, PLU, barcode and price on a selling unit row."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE product_selling_units "
            "SET label=?, unit_qty=?, plu=?, barcode=?, sell_price=? WHERE id=?",
            (label, unit_qty, plu, barcode, sell_price, su_id)
        )
        conn.commit()


def get_for_pos(barcode):
    """
    Return selling unit joined with master product and SOH for POS display.
    Includes: barcode, label, unit_qty, sell_price, su_plu, master_barcode,
    plu, cost_price, tax_rate, unit, brand, dept_name, master_soh.
    Returns None if barcode is not an active selling unit of an active product.
    """
    with db_conn() as conn:
        row = conn.execute("""
            SELECT su.barcode, su.label, su.unit_qty, su.sell_price,
                   su.plu AS su_plu,
                   p.barcode AS master_barcode, p.plu, p.cost_price,
                   p.tax_rate, p.unit, p.brand, d.name AS dept_name,
                   COALESCE(soh.quantity, 0) AS master_soh
            FROM product_selling_units su
            JOIN products p             ON su.master_barcode = p.barcode
            LEFT JOIN departments d     ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh ON soh.barcode = p.barcode
            WHERE su.barcode = ? AND su.active = 1 AND p.active = 1
        """, (barcode,)).fetchone()
        return dict(row) if row else None


def find_barcode_by_plu(plu_str):
    """Return barcode of active selling unit with matching plu column, or None."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT barcode FROM product_selling_units WHERE plu = ? AND active = 1 LIMIT 1",
            (str(plu_str),)
        ).fetchone()
        return row['barcode'] if row else None


def delete(su_id):
    """Delete a selling unit row by id."""
    with db_conn() as conn:
        conn.execute("DELETE FROM product_selling_units WHERE id=?", (su_id,))
        conn.commit()
