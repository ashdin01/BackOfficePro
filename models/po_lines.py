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
        conn.release()


def add_note(po_id: int, text: str) -> int:
    """Insert a note line (no barcode, no qty).

    barcode is NULL — SQLite FK checks are skipped for NULL by design,
    so no PRAGMA workaround is required.
    """
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO po_lines
                (po_id, barcode, description, ordered_qty, unit_cost, pack_qty, is_note)
            VALUES (?, NULL, ?, 0, 0, 1, 1)
        """, (po_id, text))
        note_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return note_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


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
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def add(po_id, barcode, description, ordered_qty, unit_cost=0, notes='', pack_qty=1):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, unit_cost, notes, pack_qty)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (po_id, barcode, description, ordered_qty, unit_cost, notes, max(1, int(pack_qty or 1))))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def update(line_id, ordered_qty, unit_cost, notes):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE po_lines SET ordered_qty=?, unit_cost=?, notes=? WHERE id=?
        """, (ordered_qty, unit_cost, notes, line_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


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
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def correct_received(line_id, new_received_qty):
    """Correct the received_qty on a line — used for partial PO corrections."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE po_lines SET received_qty=? WHERE id=?",
            (new_received_qty, line_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def delete(line_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM po_lines WHERE id = ?", (line_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def get_received_count(po_id) -> int:
    """Number of po_lines with at least one unit received."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM po_lines WHERE po_id=? AND received_qty > 0",
            (po_id,)
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.release()


def get_unreceived(po_id) -> list:
    """Lines where received_qty < ordered_qty. Returns list of dicts."""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, description, ordered_qty, received_qty "
            "FROM po_lines WHERE po_id=? AND received_qty < ordered_qty",
            (po_id,)
        ).fetchall()]
    finally:
        conn.release()


def get_on_order_units(barcodes) -> dict:
    """
    Units already committed on open (DRAFT/SENT) POs, keyed by barcode.
    For standard POs ordered_qty is cartons → multiply by pack_qty.
    For IO/RO POs ordered_qty is already units.
    Returns {barcode: float}.
    """
    if not barcodes:
        return {}
    conn = get_connection()
    try:
        ph = ','.join('?' * len(barcodes))
        rows = conn.execute(f"""
            SELECT pl.barcode,
                   COALESCE(SUM(
                       CASE WHEN po.po_type IN ('IO', 'RO')
                            THEN MAX(0.0, pl.ordered_qty - pl.received_qty)
                            ELSE MAX(0.0, pl.ordered_qty - pl.received_qty)
                                 * COALESCE(p.pack_qty, 1)
                       END
                   ), 0.0) AS on_order_units
            FROM po_lines pl
            JOIN purchase_orders po ON pl.po_id = po.id
            JOIN products p ON pl.barcode = p.barcode
            WHERE po.status IN ('DRAFT', 'SENT')
              AND pl.barcode IN ({ph})
            GROUP BY pl.barcode
        """, barcodes).fetchall()
        result = {b: 0.0 for b in barcodes}
        for r in rows:
            result[r['barcode']] = float(r['on_order_units'])
        return result
    finally:
        conn.release()


def get_on_order_total(barcode) -> int:
    """Returns total outstanding units across open POs for a single barcode."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM("
            "  CASE WHEN po.po_type IN ('RO','IO')"
            "       THEN (pl.ordered_qty - pl.received_qty)"
            "       ELSE (pl.ordered_qty - pl.received_qty) * COALESCE(p.pack_qty, 1)"
            "  END"
            "), 0) "
            "FROM po_lines pl "
            "JOIN purchase_orders po ON po.id = pl.po_id "
            "JOIN products p ON p.barcode = pl.barcode "
            "WHERE pl.barcode=? AND po.status IN ('DRAFT','SENT','PARTIAL') "
            "AND (pl.ordered_qty - pl.received_qty) > 0",
            (barcode,)
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.release()


def get_on_order_detail(barcode) -> list:
    """Returns per-PO breakdown of outstanding units for a barcode.

    Each dict has: po_number, supplier_name, qty_units, status, po_type.
    RO and IO orders store ordered_qty in units already; all others are in cartons.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT po.po_number, po.po_type, po.status, "
            "COALESCE(s.name, '—') AS supplier_name, "
            "CAST("
            "  CASE WHEN po.po_type IN ('RO','IO')"
            "       THEN (pl.ordered_qty - pl.received_qty)"
            "       ELSE (pl.ordered_qty - pl.received_qty) * COALESCE(p.pack_qty, 1)"
            "  END"
            " AS INTEGER) AS qty_units "
            "FROM po_lines pl "
            "JOIN purchase_orders po ON po.id = pl.po_id "
            "JOIN products p ON p.barcode = pl.barcode "
            "LEFT JOIN suppliers s ON s.id = po.supplier_id "
            "WHERE pl.barcode=? AND po.status IN ('DRAFT','SENT','PARTIAL') "
            "AND (pl.ordered_qty - pl.received_qty) > 0 "
            "ORDER BY po.po_number",
            (barcode,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()
