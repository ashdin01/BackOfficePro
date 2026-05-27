"""Model for the plu_barcode_map table."""
import logging
from database.connection import get_connection


def ensure_table():
    """Create the plu_barcode_map table if it does not yet exist."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plu_barcode_map (
                plu     INTEGER PRIMARY KEY,
                barcode TEXT    NOT NULL,
                mapped_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def save(plu_int: int, barcode: str):
    """Persist a PLU→barcode mapping (INSERT OR REPLACE)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO plu_barcode_map (plu, barcode, mapped_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (plu_int, barcode)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def load() -> dict:
    """Return {plu_int: barcode} from the persistent map table."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT plu, barcode FROM plu_barcode_map").fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception:
        logging.exception("plu_barcode_map.load failed")
        return {}
    finally:
        conn.release()


def delete(plu):
    """Delete a single plu_barcode_map row by PLU number."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM plu_barcode_map WHERE plu=?", (int(plu),))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def sync(barcode, plu):
    """
    Upsert plu_barcode_map so the map entry matches the products.plu value.
    Pass plu=None or '' to remove the map entry.
    """
    conn = get_connection()
    try:
        if plu:
            conn.execute(
                "INSERT INTO plu_barcode_map(plu, barcode) VALUES(?,?) "
                "ON CONFLICT(plu) DO UPDATE SET barcode=excluded.barcode",
                (int(plu), barcode)
            )
        else:
            conn.execute("DELETE FROM plu_barcode_map WHERE barcode=?", (barcode,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def get_plu_for_barcodes(barcodes) -> dict:
    """
    Return {barcode: str(plu)} for all barcodes found in plu_barcode_map.
    Only barcodes with a mapping are included in the result.
    """
    if not barcodes:
        return {}
    conn = get_connection()
    try:
        ph = ','.join('?' * len(barcodes))
        rows = conn.execute(
            f"SELECT barcode, plu FROM plu_barcode_map WHERE barcode IN ({ph})", barcodes
        ).fetchall()
        return {r['barcode']: str(r['plu']) for r in rows}
    finally:
        conn.release()


def find_barcode_by_plu(plu_int: int):
    """Return barcode for a PLU from the map table, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT barcode FROM plu_barcode_map WHERE plu = ?", (int(plu_int),)
        ).fetchone()
        return row['barcode'] if row else None
    finally:
        conn.release()


def get_plu_for_barcode(barcode) -> str | None:
    """Return str(plu) for a single barcode, or None if no mapping exists."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
        ).fetchone()
        return str(row['plu']) if row else None
    finally:
        conn.release()
