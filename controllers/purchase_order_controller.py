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

    conn = get_connection()
    try:
        plu_row = conn.execute(
            "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
        ).fetchone()
        if not plu_row:
            return None

        plu = str(plu_row[0])

        def _qty(d_from, d_to):
            row = conn.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM sales_daily
                WHERE plu = ? AND sale_date BETWEEN ? AND ?
            """, (plu, str(d_from), str(d_to))).fetchone()
            return int(row[0]) if row else 0

        return {
            "last_week":   _qty(last_week_start, last_week_end),
            "two_weeks":   _qty(two_weeks_start, two_weeks_end),
            "this_month":  _qty(month_start, today),
            "ytd":         _qty(year_start, today),
        }
    except Exception:
        return None
    finally:
        conn.close()


def get_sales_for_barcode_range(barcode, date_from, date_to):
    """
    Return total sales quantity for barcode between date_from and date_to (inclusive).
    Returns None if no PLU mapping exists, otherwise an int.
    """
    conn = get_connection()
    try:
        plu_row = conn.execute(
            "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
        ).fetchone()
        if not plu_row:
            return None
        plu = str(plu_row[0])
        row = conn.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM sales_daily
            WHERE plu = ? AND sale_date BETWEEN ? AND ?
        """, (plu, str(date_from), str(date_to))).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None
    finally:
        conn.close()


def get_sales_for_barcodes_range(barcodes, date_from, date_to):
    """
    Bulk version of get_sales_for_barcode_range.
    Returns {barcode: int|None} — None means no PLU mapping exists.
    """
    if not barcodes:
        return {}
    try:
        conn = get_connection()
        ph = ','.join('?' * len(barcodes))
        plu_rows = conn.execute(
            f"SELECT barcode, plu FROM plu_barcode_map WHERE barcode IN ({ph})",
            barcodes
        ).fetchall()
        barcode_to_plu = {r['barcode']: str(r['plu']) for r in plu_rows}

        result = {b: None for b in barcodes}
        if barcode_to_plu:
            all_plus = list(barcode_to_plu.values())
            ph2 = ','.join('?' * len(all_plus))
            sales_rows = conn.execute(f"""
                SELECT plu, COALESCE(SUM(quantity), 0) AS total
                FROM sales_daily
                WHERE plu IN ({ph2}) AND sale_date BETWEEN ? AND ?
                GROUP BY plu
            """, all_plus + [str(date_from), str(date_to)]).fetchall()
            plu_to_qty = {r['plu']: int(r['total']) for r in sales_rows}
            for barcode, plu in barcode_to_plu.items():
                result[barcode] = plu_to_qty.get(plu, 0)

        conn.close()
        return result
    except Exception:
        return {b: None for b in barcodes}


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


def close_credit_atomic(po_id, po_number, line_receipts):
    """
    Close a Credit/Return PO atomically.
    line_receipts: list of dicts with line_id, barcode, return_cartons, qty_units.
    SOH is reduced by qty_units for each line; movements are RETURN type.
    """
    conn = get_connection()
    try:
        for r in line_receipts:
            conn.execute(
                "UPDATE po_lines SET received_qty=? WHERE id=?",
                (r['return_cartons'], r['line_id'])
            )
            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (r['barcode'], -r['qty_units']))
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by)
                VALUES (?, 'RETURN', ?, ?, '', '')
            """, (r['barcode'], -r['qty_units'], po_number))
        conn.execute(
            "UPDATE purchase_orders SET status='CLOSED', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (po_id,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def receive_po_atomic(po_id, po_number, line_receipts, final_status):
    """
    Apply a full PO receipt in one atomic transaction.

    line_receipts is a list of dicts:
        line_id, barcode, new_received_qty,
        actual_cost, unit_cost, is_promo,
        qty_units   (number of individual units being received, for SOH)

    Raises on any error; the caller must not catch silently.
    """
    MOVE_RECEIPT = 'RECEIPT'
    conn = get_connection()
    try:
        for r in line_receipts:
            fields = ["received_qty=?"]
            params = [r['new_received_qty']]
            if r['actual_cost'] is not None:
                fields.append("actual_cost=?")
                params.append(r['actual_cost'])
            if r['unit_cost'] is not None:
                fields.append("unit_cost=?")
                params.append(r['unit_cost'])
            fields.append("is_promo=?")
            params.append(1 if r['is_promo'] else 0)
            params.append(r['line_id'])
            conn.execute(
                f"UPDATE po_lines SET {', '.join(fields)} WHERE id=?", params
            )

            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (r['barcode'], r['qty_units']))
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by)
                VALUES (?, ?, ?, ?, '', '')
            """, (r['barcode'], MOVE_RECEIPT, r['qty_units'], po_number))

            if r['unit_cost'] and r['unit_cost'] > 0 and not r['is_promo']:
                conn.execute(
                    "UPDATE products SET cost_price=?, updated_at=CURRENT_TIMESTAMP"
                    " WHERE barcode=?",
                    (r['unit_cost'], r['barcode'])
                )

        conn.execute(
            "UPDATE purchase_orders SET status=?, updated_at=CURRENT_TIMESTAMP"
            " WHERE id=?",
            (final_status, po_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _days_to_next_delivery(delivery_days_str, from_date=None):
    """
    Given a comma-separated delivery day string ('MON,THU'), return
    (days_ahead, next_delivery_date) for the next upcoming delivery.
    Never returns 0 — if delivery is today, returns 7 (next week).
    """
    from datetime import date, timedelta
    if from_date is None:
        from_date = date.today()
    days_map = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4, 'SAT': 5, 'SUN': 6}
    codes    = [d.strip().upper() for d in delivery_days_str.split(',') if d.strip()]
    weekdays = [days_map[d] for d in codes if d in days_map]
    if not weekdays:
        return 3, from_date + timedelta(days=3)
    today_wd = from_date.weekday()
    min_days = min(((dw - today_wd) % 7) or 7 for dw in weekdays)
    return min_days, from_date + timedelta(days=min_days)


def get_milk_order_recommendations(supplier_id):
    """
    Return demand-forecast order quantities for Dairy/Milk products linked to
    supplier_id.  Requires delivery_days to be set on the supplier; returns []
    if not configured (caller falls back to standard reorder logic).

    Algorithm per product:
        avg_daily    = total units sold (last 14 days) / 14
        cover_days   = days_to_next_delivery + 1  (safety buffer)
        needed_units = max(0, avg_daily * cover_days - current_soh)
        cartons      = ceil(needed_units / pack_qty), minimum 1
    """
    from datetime import date, timedelta
    SAFETY_DAYS  = 2
    SALES_WINDOW = 14

    conn = get_connection()
    try:
        sup = conn.execute(
            "SELECT delivery_days FROM suppliers WHERE id=?", (supplier_id,)
        ).fetchone()
        if not sup or not (sup['delivery_days'] or '').strip():
            return []

        days_ahead, next_delivery = _days_to_next_delivery(sup['delivery_days'])
        cover_days   = days_ahead + SAFETY_DAYS
        today        = date.today()
        window_start = today - timedelta(days=SALES_WINDOW)

        products = conn.execute("""
            SELECT p.barcode, p.description,
                   COALESCE(p.cost_price, 0)   AS cost_price,
                   COALESCE(p.pack_qty, 1)     AS pack_qty,
                   COALESCE(p.pack_unit, 'EA') AS pack_unit,
                   COALESCE(soh.quantity, 0)   AS on_hand,
                   p.supplier_sku
            FROM products p
            JOIN product_groups  pg  ON p.group_id       = pg.id
            JOIN departments     d   ON pg.department_id = d.id
            LEFT JOIN stock_on_hand soh ON p.barcode     = soh.barcode
            WHERE p.supplier_id = ?
              AND p.active = 1
              AND UPPER(d.name)  = 'DAIRY'
              AND UPPER(pg.name) = 'MILK'
            ORDER BY p.description
        """, (supplier_id,)).fetchall()

        if not products:
            return []

        barcodes = [p['barcode'] for p in products]
        ph       = ','.join('?' * len(barcodes))
        plu_rows = conn.execute(
            f"SELECT barcode, plu FROM plu_barcode_map WHERE barcode IN ({ph})", barcodes
        ).fetchall()
        barcode_to_plu = {r['barcode']: str(r['plu']) for r in plu_rows}

        # Fallback: use products.sku for any unmapped barcodes
        for p in products:
            if p['barcode'] not in barcode_to_plu:
                row = conn.execute(
                    "SELECT sku FROM products WHERE barcode=?", (p['barcode'],)
                ).fetchone()
                if row and row['sku']:
                    barcode_to_plu[p['barcode']] = str(row['sku'])

        plu_sales = {}
        all_plus  = list(barcode_to_plu.values())
        if all_plus:
            ph2 = ','.join('?' * len(all_plus))
            for row in conn.execute(f"""
                SELECT plu, COALESCE(SUM(quantity), 0) AS total
                FROM sales_daily
                WHERE plu IN ({ph2}) AND sale_date BETWEEN ? AND ?
                GROUP BY plu
            """, all_plus + [str(window_start), str(today)]).fetchall():
                plu_sales[row['plu']] = float(row['total'])

        recs = []
        for p in products:
            plu          = barcode_to_plu.get(p['barcode'])
            total_14day  = plu_sales.get(plu, 0.0) if plu else 0.0
            avg_daily    = total_14day / SALES_WINDOW
            needed_units = max(0.0, avg_daily * cover_days - float(p['on_hand']))
            pack_qty     = max(1, int(p['pack_qty']))
            cartons      = max(1, math.ceil(needed_units / pack_qty))
            recs.append({
                'barcode':          p['barcode'],
                'description':      p['description'],
                'cost_price':       p['cost_price'],
                'pack_qty':         pack_qty,
                'pack_unit':        p['pack_unit'],
                'on_hand':          float(p['on_hand']),
                'supplier_sku':     p['supplier_sku'],
                'cartons':          cartons,
                'avg_daily':        round(avg_daily, 1),
                'cover_days':       cover_days,
                'days_to_delivery': days_ahead,
                'next_delivery':    next_delivery,
                'has_sales_data':   plu is not None and total_14day > 0,
            })
        return recs
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
