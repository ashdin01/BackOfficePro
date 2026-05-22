import math
from datetime import date, timedelta
from database.connection import get_connection
import models.purchase_order as po_model
import models.po_lines as lines_model


def _on_order_units(conn, barcodes):
    """
    Units already committed on open (DRAFT/SENT) POs, keyed by barcode.
    For standard POs ordered_qty is cartons → multiply by pack_qty.
    For IO/RO POs ordered_qty is already units.
    """
    if not barcodes:
        return {}
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


def get_reorder_recommendations(supplier_id):
    """
    Products linked to supplier_id whose effective stock (SOH + on open POs)
    is at or below their reorder point.
    Returns dicts with barcode, description, reorder_point, reorder_max,
    cost_price, on_hand, on_order, effective_stock, pack_qty, pack_unit, supplier_sku.
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
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

        if not rows:
            return []

        barcodes   = [r['barcode'] for r in rows]
        on_order   = _on_order_units(conn, barcodes)
        result     = []
        for r in rows:
            on_order_qty    = on_order.get(r['barcode'], 0.0)
            effective_stock = float(r['on_hand']) + on_order_qty
            if effective_stock <= float(r['reorder_point']):
                d = dict(r)
                d['on_order']       = on_order_qty
                d['effective_stock'] = effective_stock
                result.append(d)
        return result
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
    If supplier_id is given, return all products linked to that supplier via
    product_suppliers (not just those whose default supplier matches).
    Rows include: supplier_name, barcode, description, pack_qty, pack_unit, cost_price.
    """
    conn = get_connection()
    try:
        if supplier_id:
            return conn.execute("""
                SELECT COALESCE(s.name, '') AS supplier_name,
                       p.barcode, p.description,
                       COALESCE(ps.pack_qty, p.pack_qty, 1) AS pack_qty,
                       COALESCE(ps.pack_unit, p.pack_unit, 'EA') AS pack_unit,
                       COALESCE(p.cost_price, 0.0) AS cost_price
                FROM products p
                JOIN product_suppliers ps ON p.barcode = ps.barcode AND ps.supplier_id = ?
                JOIN suppliers s ON s.id = ?
                WHERE p.active = 1
                ORDER BY p.description ASC
            """, (supplier_id, supplier_id)).fetchall()
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


def receive_po_atomic(po_id, po_number, line_receipts, final_status,
                      supplier_invoice_number='', charges=None):
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
            "UPDATE purchase_orders SET status=?, supplier_invoice_number=?,"
            " updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (final_status, supplier_invoice_number, po_id)
        )
        if charges:
            conn.execute("DELETE FROM po_charges WHERE po_id=?", (po_id,))
            for c in charges:
                conn.execute(
                    "INSERT INTO po_charges (po_id, description, tax_rate, amount_inc_tax)"
                    " VALUES (?,?,?,?)",
                    (po_id, c['description'], c['tax_rate'], c['amount_inc_tax'])
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

        milk_on_order = _on_order_units(conn, [p['barcode'] for p in products])

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
            plu              = barcode_to_plu.get(p['barcode'])
            total_14day      = plu_sales.get(plu, 0.0) if plu else 0.0
            avg_daily        = total_14day / SALES_WINDOW
            on_hand          = float(p['on_hand'])
            on_order         = milk_on_order.get(p['barcode'], 0.0)
            effective_stock  = on_hand + on_order
            needed_units     = max(0.0, avg_daily * cover_days - effective_stock)
            pack_qty         = max(1, int(p['pack_qty']))
            cartons          = max(1, math.ceil(needed_units / pack_qty))
            recs.append({
                'barcode':          p['barcode'],
                'description':      p['description'],
                'cost_price':       p['cost_price'],
                'pack_qty':         pack_qty,
                'pack_unit':        p['pack_unit'],
                'on_hand':          on_hand,
                'on_order':         on_order,
                'effective_stock':  effective_stock,
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


# ── PDF / Email / CSV export ──────────────────────────────────────────────────

def _po_pdf_path(po):
    """Return the full output path for a PO PDF, creating the directory if needed."""
    import os
    import models.settings as settings_model
    folder = (settings_model.get_setting('po_pdf_path') or '').strip()
    if not folder:
        folder = os.path.join(os.path.expanduser('~'), 'Documents', 'BackOfficePro', 'PurchaseOrders')
    os.makedirs(folder, exist_ok=True)
    filename = f"{po['po_number']}_{po['supplier_name'].replace(' ', '_')}.pdf"
    return os.path.join(folder, filename)


def generate_po_pdf_to_disk(po_id):
    """Generate the PO PDF to the configured folder. Return the full path."""
    import models.purchase_order as po_model
    from utils.po_pdf import generate_po_pdf
    po = po_model.get_by_id(po_id)
    path = _po_pdf_path(po)
    generate_po_pdf(po_id, path)
    return path


def send_po_email(po_id, supplier_email):
    """Generate PDF, email to supplier, and mark PO as SENT. Return the PDF path."""
    import logging
    import models.purchase_order as po_model
    from utils.email_graph import send_purchase_order
    from config.constants import PO_STATUS_SENT
    path = generate_po_pdf_to_disk(po_id)
    send_purchase_order(po_id=po_id, to_address=supplier_email, pdf_path=path)
    po_model.update_status(po_id, PO_STATUS_SENT)
    logging.info(f"PO {po_id} emailed to {supplier_email}, marked SENT")
    return path


def write_po_csv(po_id, output_path):
    """Write a CSV of PO lines to output_path."""
    import csv
    import models.purchase_order as po_model
    import models.po_lines as lines_model
    import models.product as product_model
    import models.stock_on_hand as stock_model
    import models.supplier as supplier_model

    po = po_model.get_by_id(po_id)
    supplier = supplier_model.get_by_id(po['supplier_id']) if po['supplier_id'] else None
    sup_name  = po['supplier_name'] or ''
    sup_email = (supplier['email_orders'] or '') if supplier and supplier['email_orders'] else ''
    lines = lines_model.get_by_po(po_id)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Supplier', sup_name])
        writer.writerow(['Email', sup_email])
        writer.writerow(['PO Number', po['po_number']])
        writer.writerow(['Status', po['status']])
        writer.writerow([])
        writer.writerow(['Barcode', 'Description', 'Units per Carton', 'Total Units',
                         'SOH (Actual)', 'SOH (System)', 'Variance (Actual less System)'])
        for line in lines:
            if line['is_note']:
                writer.writerow(['', f'NOTE: {line["description"]}', '', '', '', '', ''])
                continue
            product  = product_model.get_by_barcode(line['barcode'])
            pack_qty  = int(product['pack_qty']) if product and product['pack_qty'] else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
            soh      = stock_model.get_by_barcode(line['barcode'])
            on_hand  = int(soh['quantity']) if soh else 0
            total_units = int(line['ordered_qty']) * pack_qty
            writer.writerow([f'="{line["barcode"]}"', line['description'],
                             f'{pack_qty} x {pack_unit}', total_units, '', on_hand, ''])


# ── Recommendation helpers ────────────────────────────────────────────────────

def auto_populate_po_lines(po_id, supplier_id):
    """
    Populate a new PO with milk-forecast, reorder-point, and auto-reorder lines.
    Returns a banner text string summarising what was added.
    """
    import models.po_lines as lines_model
    banner_parts = []

    # Milk demand forecast
    milk_recs    = get_milk_order_recommendations(supplier_id)
    milk_barcodes = set()
    if milk_recs:
        first        = milk_recs[0]
        delivery_str = first['next_delivery'].strftime('%a %-d %b')
        safety       = first['cover_days'] - first['days_to_delivery']
        for r in milk_recs:
            on_order_str = f"  |  On order: {int(r['on_order'])}" if r['on_order'] > 0 else ""
            note = (
                f"🥛 Milk forecast: avg {r['avg_daily']}/day × {r['cover_days']} days "
                f"(delivery {delivery_str} + {safety} day buffer)"
                f"  |  SOH: {int(r['on_hand'])}{on_order_str}"
                f"  |  {r['pack_qty']} × {r['pack_unit']}"
            )
            if not r['has_sales_data']:
                note += "  ⚠ no sales history — defaulting to 1 carton"
            lines_model.add(
                po_id=po_id, barcode=r['barcode'], description=r['description'],
                ordered_qty=r['cartons'], unit_cost=r['cost_price'],
                notes=note, pack_qty=r['pack_qty'],
            )
            milk_barcodes.add(r['barcode'])
        banner_parts.append(
            f"🥛 {len(milk_recs)} milk line(s) — covering {first['days_to_delivery']} days "
            f"to delivery ({delivery_str}) + {safety} day buffer"
        )

    # Standard reorder points (skip milk products already added)
    recs = [r for r in get_reorder_recommendations(supplier_id) if r['barcode'] not in milk_barcodes]
    for r in recs:
        pack_qty  = int(r['pack_qty']) if r['pack_qty'] else 1
        pack_unit = r['pack_unit'] or 'EA'
        order_units = calc_order_units(r['reorder_max'], 0, r['effective_stock'])
        lines_model.add(
            po_id=po_id, barcode=r['barcode'], description=r['description'],
            ordered_qty=cartons_needed(order_units, pack_qty), unit_cost=r['cost_price'],
            notes=carton_note(pack_qty, pack_unit, r['barcode']), pack_qty=pack_qty,
        )
    if recs:
        banner_parts.append(f"💡 {len(recs)} reorder line(s) from reorder points")

    # Auto-reorder items not yet on this PO
    existing_barcodes = {l['barcode'] for l in lines_model.get_by_po(po_id)}
    auto_added = 0
    for ar in get_auto_reorder_items(supplier_id):
        if ar['barcode'] in existing_barcodes:
            continue
        auto_pack_qty = int(ar['pack_qty']) if ar['pack_qty'] else 1
        lines_model.add(
            po_id=po_id, barcode=ar['barcode'], description=ar['description'],
            ordered_qty=1, unit_cost=ar['cost_price'],
            notes=carton_note(auto_pack_qty, ar['pack_unit'], ar['barcode']),
            pack_qty=auto_pack_qty,
        )
        auto_added += 1
    if auto_added:
        banner_parts.append(f"{auto_added} on-reorder item(s) at 1 carton")

    if not banner_parts:
        return "✓ All stock levels are above reorder points for this supplier."
    return "  |  ".join(banner_parts)


def reload_reorder_recommendations(po_id, supplier_id):
    """
    Add new reorder recommendations to an existing PO.
    Returns None if no products are at reorder point, 0 if all are already on the PO,
    or the positive count of lines added.
    """
    import models.po_lines as lines_model
    recs = get_reorder_recommendations(supplier_id)
    if not recs:
        return None
    existing  = {l['barcode'] for l in lines_model.get_by_po(po_id)}
    new_recs  = [r for r in recs if r['barcode'] not in existing]
    if not new_recs:
        return 0
    for r in new_recs:
        pack_qty  = int(r['pack_qty']) if r['pack_qty'] else 1
        pack_unit = r['pack_unit'] or 'EA'
        order_units = calc_order_units(r['reorder_max'], 0, r['effective_stock'])
        lines_model.add(
            po_id=po_id, barcode=r['barcode'], description=r['description'],
            ordered_qty=cartons_needed(order_units, pack_qty), unit_cost=r['cost_price'],
            notes=carton_note(pack_qty, pack_unit, r['barcode']), pack_qty=pack_qty,
        )
    return len(new_recs)


# ── AddLine product lookup ────────────────────────────────────────────────────

def lookup_product_for_po(barcode, po_id, supplier_id, unit_mode):
    """
    Validate a barcode for addition to a PO line and calculate a suggested quantity.

    Returns a dict with product info on success, or None if the barcode is not found.
    Raises ValueError with a structured code on validation failures:
      'already_on_po:{line_num}:{description}' — product is already on this PO
      'not_linked:{supplier_name}'              — product is not linked to the PO supplier
    """
    import models.po_lines      as lines_model
    import models.product        as product_model
    import models.product_suppliers as ps_model
    import models.stock_on_hand as stock_model
    import models.supplier       as supplier_model

    existing_lines = lines_model.get_by_po(po_id)
    for line_num, existing in enumerate(existing_lines, start=1):
        if existing['barcode'] == barcode:
            raise ValueError(f"already_on_po:{line_num}:{existing['description']}")

    product = product_model.get_by_barcode(barcode)
    if not product:
        return None

    if supplier_id:
        linked = [r['supplier_id'] for r in ps_model.get_by_barcode(barcode)]
        if supplier_id not in linked:
            sup     = supplier_model.get_by_id(supplier_id)
            po_name = sup['name'] if sup else "Unknown"
            raise ValueError(f"not_linked:{po_name}")

    soh          = stock_model.get_by_barcode(barcode)
    on_hand      = int(soh['quantity']) if soh else 0
    reorder_max  = int(product['reorder_max']) if product['reorder_max'] else 0
    pack_qty     = int(product['pack_qty'])    if product['pack_qty']    else 1
    pack_unit    = product['pack_unit'] or 'EA'
    reorder_point = int(product['reorder_point'])

    if unit_mode:
        suggested_qty = 1
    else:
        order_units   = max(1, reorder_max - on_hand) if reorder_max > 0 else pack_qty
        suggested_qty = max(1, math.ceil(order_units / pack_qty))

    return {
        'description':    product['description'],
        'cost_price':     product['cost_price'],
        'on_hand':        on_hand,
        'reorder_point':  reorder_point,
        'pack_qty':       pack_qty,
        'pack_unit':      pack_unit,
        'suggested_qty':  suggested_qty,
    }
