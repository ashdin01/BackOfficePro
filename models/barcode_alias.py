from database.connection import get_connection


def resolve(barcode):
    """Return master barcode if alias exists, otherwise return original."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT master_barcode FROM barcode_aliases WHERE alias_barcode = ?",
            (barcode,)
        ).fetchone()
        return row['master_barcode'] if row else barcode
    finally:
        conn.close()


def get_aliases(master_barcode):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM barcode_aliases WHERE master_barcode = ? ORDER BY alias_barcode",
            (master_barcode,)
        ).fetchall()
    finally:
        conn.close()


def add(alias_barcode, master_barcode, description=""):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO barcode_aliases (alias_barcode, master_barcode, description) VALUES (?,?,?)",
            (alias_barcode, master_barcode, description)
        )
        conn.commit()
    finally:
        conn.close()


def delete(alias_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM barcode_aliases WHERE id = ?", (alias_id,))
        conn.commit()
    finally:
        conn.close()
