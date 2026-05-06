import math
from datetime import date, timedelta
from database.connection import get_connection
import models.purchase_order as po_model
import models.po_lines as lines_model


def get_reorder_recommendations(supplier_id):
    """
    Products linked to supplier_id whose stock is at or below their reorder point.
    Returns rows with barcode, description, reorder_point, reorder_max, cost_price,
    on_hand, pack_qty, pack_unit, supplier_sku.
    """
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT p.barcode, p.description, p.reorder_point,
                   COALESCE(p.reorder_max, 0) AS reorder_max,
                   p.cost_price, COALESCE(s.quantity, 0) AS on_hand,
                   COALESCE(p.pack_qty, 1) AS pack_qty,
                   COALESCE(p.pack_unit, 'EA') AS pack_unit,
                   p.supplier_sku
            FROM products p
            LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
            WHERE p.supplier_id = ?
              AND p.active = 1
              AND COALESCE(s.quantity, 0) <= p.reorder_point
              AND p.reorder_point > 0
            ORDER BY p.description
        """, (supplier_id,)).fetchall()
    finally:
        conn.close()


def get_auto_reorder_items(supplier_id):
    """Products flagged auto_reorder = 1 for this supplier."""
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT p.barcode, p.description, p.reorder_point,
                   COALESCE(p.reorder_max, 0) AS reorder_max,
                   p.cost_price, COALESCE(s.quantity, 0) AS on_hand,
                   COALESCE(p.pack_qty, 1) AS pack_qty,
                   COALESCE(p.pack_unit, 'EA') AS pack_unit,
                   p.supplier_sku
            FROM products p
            LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
            WHERE p.supplier_id = ? AND p.auto_reorder = 1 AND p.active = 1
            ORDER BY p.description
        """, (supplier_id,)).fetchall()
    finally:
        conn.close()


def get_items_for_supplier(supplier_id=None):
    """
    Return active products for the item lookup dialog.
    If supplier_id is given, restrict to products whose default supplier matches.
    Rows include: supplier_name, barcode, description, pack_qty, pack_unit, cost_price.
    """
    conn = get_connection()
    try:
        if supplier_id:
            return conn.execute("""
                SELECT COALESCE(s.name, '') AS supplier_name,
                       p.barcode, p.description,
                       COALESCE(p.pack_qty, 1) AS pack_qty,
                       COALESCE(p.pack_unit, 'EA') AS pack_unit,
                       COALESCE(p.cost_price, 0.0) AS cost_price
                FROM products p
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                WHERE p.active = 1 AND p.supplier_id = ?
                ORDER BY p.description ASC
            """, (supplier_id,)).fetchall()
        else:
            return conn.execute("""
                SELECT COALESCE(s.name, '') AS supplier_name,
                       p.barcode, p.description,
                       COALESCE(p.pack_qty, 1) AS pack_qty,
                       COALESCE(p.pack_unit, 'EA') AS pack_unit,
                       COALESCE(p.cost_price, 0.0) AS cost_price
                FROM products p
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                WHERE p.active = 1
                ORDER BY supplier_name ASC, p.description ASC
            """).fetchall()
    finally:
        conn.close()


def get_sales_for_barcode(barcode):
    """
    Return a dict of sales totals (last_week, two_weeks, this_month, ytd)
    by looking up the product's PLU in the plu_barcode_map and aggregating sales_daily.
    Returns None if no PLU mapping exists.
    """
    today = date.today()
    days_since_monday = today.weekday()
    this_week_start = today - timedelta(days=days_since_monday)
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end   = this_week_start - timedelta(days=1)
    two_weeks_start = last_week_start - timedelta(days=7)
    two_weeks_end   = last_week_start - timedelta(days=1)
    month_start = today.replace(day=1)
    year_start  = today.replace(month=1, day=1)

    try:
        conn = get_connection()
        plu_row = conn.execute(
            "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
        ).fetchone()
        if not plu_row:
            conn.close()
            return None

        plu = str(plu_row[0])

        def _qty(d_from, d_to):
            row = conn.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM sales_daily
                WHERE plu = ? AND sale_date BETWEEN ? AND ?
            """, (plu, str(d_from), str(d_to))).fetchone()
            return int(row[0]) if row else 0

        result = {
            "last_week":   _qty(last_week_start, last_week_end),
            "two_weeks":   _qty(two_weeks_start, two_weeks_end),
            "this_month":  _qty(month_start, today),
            "ytd":         _qty(year_start, today),
        }
        conn.close()
        return result
    except Exception:
        return None


def get_sales_for_barcode_range(barcode, date_from, date_to):
    """
    Return total sales quantity for barcode between date_from and date_to (inclusive).
    Returns None if no PLU mapping exists, otherwise an int.
    """
    try:
        conn = get_connection()
        plu_row = conn.execute(
            "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
        ).fetchone()
        if not plu_row:
            conn.close()
            return None
        plu = str(plu_row[0])
        row = conn.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM sales_daily
            WHERE plu = ? AND sale_date BETWEEN ? AND ?
        """, (plu, str(date_from), str(date_to))).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return None


def get_received_line_count(po_id):
    """Number of po_lines with at least one unit received."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM po_lines WHERE po_id=? AND received_qty > 0",
            (po_id,)
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def get_po_with_supplier(po_id):
    """Return the PO row joined with supplier name as a dict, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT po.*, s.name AS supplier_name "
            "FROM purchase_orders po "
            "JOIN suppliers s ON s.id = po.supplier_id "
            "WHERE po.id=?",
            (po_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_unreceived_lines(po_id):
    """Lines where received_qty < ordered_qty. Returns list of dicts."""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, description, ordered_qty, received_qty "
            "FROM po_lines WHERE po_id=? AND received_qty < ordered_qty",
            (po_id,)
        ).fetchall()]
    finally:
        conn.close()


def close_po_force(po_id, unreceived_line_ids, reason):
    """Mark listed lines NOT SUPPLIED and set PO status to RECEIVED atomically."""
    conn = get_connection()
    try:
        note = f"NOT SUPPLIED: {reason}"
        for line_id in unreceived_line_ids:
            conn.execute("UPDATE po_lines SET notes=? WHERE id=?", (note, line_id))
        conn.execute(
            "UPDATE purchase_orders SET status='RECEIVED', "
            "received_at=CURRENT_TIMESTAMP WHERE id=?",
            (po_id,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cartons_needed(reorder_qty, pack_qty):
    pack_qty = pack_qty if pack_qty and pack_qty > 0 else 1
    return max(1, math.ceil(reorder_qty / pack_qty))


def calc_order_units(reorder_max, reorder_qty, on_hand):
    reorder_max = reorder_max or 0
    on_hand = on_hand or 0
    if reorder_max > 0:
        needed = reorder_max - on_hand
        return max(1, int(needed))
    return max(1, int(reorder_qty or 1))


def carton_note(pack_qty, pack_unit, barcode):
    pack_qty = pack_qty if pack_qty and pack_qty > 0 else 1
    return f"{pack_qty} × {pack_unit}  |  barcode: {barcode}"
