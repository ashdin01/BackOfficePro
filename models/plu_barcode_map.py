"""Model for the plu_barcode_map table."""
import logging
from database.connection import db_conn


def ensure_table():
    """Create the plu_barcode_map table if it does not yet exist."""
    with db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plu_barcode_map (
                plu     INTEGER PRIMARY KEY,
                barcode TEXT    NOT NULL,
                mapped_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def save(plu_int: int, barcode: str):
    """Persist a PLU→barcode mapping (INSERT OR REPLACE)."""
    with db_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO plu_barcode_map (plu, barcode, mapped_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (plu_int, barcode)
        )
        conn.commit()


def load() -> dict:
    """Return {plu_int: barcode} from the persistent map table."""
    with db_conn() as conn:
        try:
            rows = conn.execute("SELECT plu, barcode FROM plu_barcode_map").fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception:
            logging.exception("plu_barcode_map.load failed")
            return {}


def delete(plu):
    """Delete a single plu_barcode_map row by PLU number."""
    with db_conn() as conn:
        conn.execute("DELETE FROM plu_barcode_map WHERE plu=?", (int(plu),))
        conn.commit()


def sync(barcode, plu):
    """
    Upsert plu_barcode_map so the map entry matches the products.plu value.
    Pass plu=None or '' to remove the map entry.
    """
    with db_conn() as conn:
        if plu:
            conn.execute(
                "INSERT INTO plu_barcode_map(plu, barcode) VALUES(?,?) "
                "ON CONFLICT(plu) DO UPDATE SET barcode=excluded.barcode",
                (int(plu), barcode)
            )
        else:
            conn.execute("DELETE FROM plu_barcode_map WHERE barcode=?", (barcode,))
        conn.commit()


def get_plu_for_barcodes(barcodes) -> dict:
    """
    Return {barcode: str(plu)} for all barcodes found in plu_barcode_map.
    Only barcodes with a mapping are included in the result.
    """
    if not barcodes:
        return {}
    with db_conn() as conn:
        ph = ','.join('?' * len(barcodes))
        rows = conn.execute(
            f"SELECT barcode, plu FROM plu_barcode_map WHERE barcode IN ({ph})", barcodes
        ).fetchall()
        return {r['barcode']: str(r['plu']) for r in rows}


def find_barcode_by_plu(plu_int: int):
    """Return barcode for a PLU from the map table, or None."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT barcode FROM plu_barcode_map WHERE plu = ?", (int(plu_int),)
        ).fetchone()
        return row['barcode'] if row else None


def get_plu_for_barcode(barcode) -> str | None:
    """Return str(plu) for a single barcode, or None if no mapping exists."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
        ).fetchone()
        return str(row['plu']) if row else None
