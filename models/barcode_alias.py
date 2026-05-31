from database.connection import db_conn


def resolve(barcode):
    """Return master barcode if alias exists, otherwise return original."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT master_barcode FROM barcode_aliases WHERE alias_barcode = ?",
            (barcode,)
        ).fetchone()
        return row['master_barcode'] if row else barcode


def get_aliases(master_barcode):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM barcode_aliases WHERE master_barcode = ? ORDER BY alias_barcode",
            (master_barcode,)
        ).fetchall()


def add(alias_barcode, master_barcode, description=""):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO barcode_aliases (alias_barcode, master_barcode, description) VALUES (?,?,?)",
            (alias_barcode, master_barcode, description)
        )
        conn.commit()


def delete(alias_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM barcode_aliases WHERE id = ?", (alias_id,))
        conn.commit()
