from database.connection import get_connection


def get_by_po(po_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM po_lines WHERE po_id = ? ORDER BY id", (po_id,)
        ).fetchall()
    finally:
        conn.close()


def add(po_id, barcode, description, ordered_qty, unit_cost=0, notes=''):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, unit_cost, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (po_id, barcode, description, ordered_qty, unit_cost, notes))
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


def receive(line_id, received_qty, actual_cost=None):
    conn = get_connection()
    try:
        if actual_cost is not None:
            conn.execute(
                "UPDATE po_lines SET received_qty=?, actual_cost=? WHERE id=?",
                (received_qty, actual_cost, line_id)
            )
        else:
            conn.execute(
                "UPDATE po_lines SET received_qty=? WHERE id=?",
                (received_qty, line_id)
            )
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
