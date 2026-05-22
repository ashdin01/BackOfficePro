import sqlite3
from config.settings import DATABASE_PATH
from database.connection import get_connection


def get_by_po(po_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM po_lines WHERE po_id=?"
            " ORDER BY COALESCE(sort_order, id), id",
            (po_id,)
        ).fetchall()
    finally:
        conn.close()


def add_note(po_id: int, text: str) -> int:
    """Insert a note line (no barcode, no qty).

    Uses a raw connection rather than get_connection() because note lines store
    an empty string barcode, which violates the FK constraint on products(barcode)
    that get_connection() enforces via PRAGMA foreign_keys = ON.
    """
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        conn.execute("""
            INSERT INTO po_lines
                (po_id, barcode, description, ordered_qty, unit_cost, pack_qty, is_note)
            VALUES (?, '', ?, 0, 0, 1, 1)
        """, (po_id, text))
        note_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return note_id
    finally:
        conn.close()


def renumber_sort_order(po_id: int, ordered_ids: list):
    """Set sort_order = 10, 20, 30... for lines in the given id order."""
    conn = get_connection()
    try:
        for i, line_id in enumerate(ordered_ids):
            conn.execute(
                "UPDATE po_lines SET sort_order=? WHERE id=? AND po_id=?",
                ((i + 1) * 10, line_id, po_id)
            )
        conn.commit()
    finally:
        conn.close()


def add(po_id, barcode, description, ordered_qty, unit_cost=0, notes='', pack_qty=1):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, unit_cost, notes, pack_qty)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (po_id, barcode, description, ordered_qty, unit_cost, notes, max(1, int(pack_qty or 1))))
        conn.commit()
    finally:
        conn.close()


def update(line_id, ordered_qty, unit_cost, notes):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE po_lines SET ordered_qty=?, unit_cost=?, notes=? WHERE id=?
        """, (ordered_qty, unit_cost, notes, line_id))
        conn.commit()
    finally:
        conn.close()


def receive(line_id, received_qty, actual_cost=None, unit_cost=None, is_promo=None):
    conn = get_connection()
    try:
        fields = ["received_qty=?"]
        params = [received_qty]
        if actual_cost is not None:
            fields.append("actual_cost=?")
            params.append(actual_cost)
        if unit_cost is not None:
            fields.append("unit_cost=?")
            params.append(unit_cost)
        if is_promo is not None:
            fields.append("is_promo=?")
            params.append(1 if is_promo else 0)
        params.append(line_id)
        conn.execute(f"UPDATE po_lines SET {', '.join(fields)} WHERE id=?", params)
        conn.commit()
    finally:
        conn.close()


def correct_received(line_id, new_received_qty):
    """Correct the received_qty on a line — used for partial PO corrections."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE po_lines SET received_qty=? WHERE id=?",
            (new_received_qty, line_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete(line_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM po_lines WHERE id = ?", (line_id,))
        conn.commit()
    finally:
        conn.close()
