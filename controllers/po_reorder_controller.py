"""Reorder recommendation and demand-forecast logic for purchase orders."""
import math
from datetime import date, timedelta
import models.po_lines as lines_model
import models.sales_daily as sales_daily_model
import models.plu_barcode_map as plu_map_model
import models.product_queries as product_queries_model
import models.supplier as supplier_model


def get_reorder_recommendations(supplier_id) -> list[dict]:
    """
    Products linked to supplier_id whose effective stock (SOH + on open POs)
    is at or below their reorder point.
    Returns dicts with barcode, description, reorder_point, reorder_max,
    cost_price, on_hand, on_order, effective_stock, pack_qty, pack_unit, supplier_sku.
    """
    candidates = product_queries_model.get_reorder_candidates(supplier_id)
    if not candidates:
        return []
    on_order = lines_model.get_on_order_units([r['barcode'] for r in candidates])
    result = []
    for r in candidates:
        on_order_qty    = on_order.get(r['barcode'], 0.0)
        effective_stock = float(r['on_hand']) + on_order_qty
        if effective_stock <= float(r['reorder_point']):
            d = dict(r)
            d['on_order']        = on_order_qty
            d['effective_stock'] = effective_stock
            result.append(d)
    return result


def get_auto_reorder_items(supplier_id) -> list[dict]:
    """Products flagged auto_reorder = 1 for this supplier."""
    return product_queries_model.get_auto_reorder_items(supplier_id)


def get_items_for_supplier(supplier_id=None) -> list[dict]:
    """
    Return active products for the item lookup dialog.
    If supplier_id is given, return all products linked to that supplier via
    product_suppliers (not just those whose default supplier matches).
    Rows include: supplier_name, barcode, description, pack_qty, pack_unit, cost_price.
    """
    return product_queries_model.get_items_for_supplier(supplier_id)


def get_sales_for_barcode(barcode) -> dict | None:
    """
    Return a dict of sales totals (last_week, two_weeks, this_month, ytd)
    by looking up the product's PLU in the plu_barcode_map and aggregating sales_daily.
    Returns None if no PLU mapping exists.
    """
    return sales_daily_model.get_sales_for_barcode(barcode)


def get_sales_for_barcode_range(barcode, date_from, date_to) -> int | None:
    """
    Return total sales quantity for barcode between date_from and date_to (inclusive).
    Returns None if no PLU mapping exists, otherwise an int.
    """
    return sales_daily_model.get_sales_for_barcode_range(barcode, date_from, date_to)


def get_sales_for_barcodes_range(barcodes, date_from, date_to) -> dict:
    """
    Bulk version of get_sales_for_barcode_range.
    Returns {barcode: int|None} — None means no PLU mapping exists.
    """
    return sales_daily_model.get_sales_for_barcodes_range(barcodes, date_from, date_to)


def get_received_line_count(po_id) -> int:
    """Number of po_lines with at least one unit received."""
    return lines_model.get_received_count(po_id)


def _days_to_next_delivery(delivery_days_str, from_date=None) -> tuple[int, date]:
    """
    Given a comma-separated delivery day string ('MON,THU'), return
    (days_ahead, next_delivery_date) for the next upcoming delivery.
    Never returns 0 — if delivery is today, returns 7 (next week).
    """
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


def get_milk_order_recommendations(supplier_id) -> list[dict]:
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
    SAFETY_DAYS  = 2
    SALES_WINDOW = 14

    delivery_days = supplier_model.get_delivery_days(supplier_id)
    if not delivery_days:
        return []

    days_ahead, next_delivery = _days_to_next_delivery(delivery_days)
    cover_days   = days_ahead + SAFETY_DAYS
    today        = date.today()
    window_start = today - timedelta(days=SALES_WINDOW)

    products = product_queries_model.get_milk_products(supplier_id)
    if not products:
        return []

    milk_on_order  = lines_model.get_on_order_units([p['barcode'] for p in products])
    barcodes       = [p['barcode'] for p in products]
    barcode_to_plu = plu_map_model.get_plu_for_barcodes(barcodes)

    # Fallback: use products.sku for any unmapped barcodes
    for p in products:
        if p['barcode'] not in barcode_to_plu:
            sku = product_queries_model.get_sku(p['barcode'])
            if sku:
                barcode_to_plu[p['barcode']] = str(sku)

    plu_sales: dict[str, float] = {}
    if barcode_to_plu:
        sales_map = sales_daily_model.get_sales_for_barcodes_range(barcodes, window_start, today)
        for barcode, plu in barcode_to_plu.items():
            qty = sales_map.get(barcode)
            if qty is not None:
                plu_sales[plu] = plu_sales.get(plu, 0.0) + float(qty)

    recs = []
    for p in products:
        plu             = barcode_to_plu.get(p['barcode'])
        total_14day     = plu_sales.get(plu, 0.0) if plu else 0.0
        avg_daily       = total_14day / SALES_WINDOW
        on_hand         = float(p['on_hand'])
        on_order        = milk_on_order.get(p['barcode'], 0.0)
        effective_stock = on_hand + on_order
        needed_units    = max(0.0, avg_daily * cover_days - effective_stock)
        pack_qty        = max(1, int(p['pack_qty']))
        cartons         = max(1, math.ceil(needed_units / pack_qty))
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


def cartons_needed(reorder_qty, pack_qty) -> int:
    pack_qty = pack_qty if pack_qty and pack_qty > 0 else 1
    return max(1, math.ceil(reorder_qty / pack_qty))


def calc_order_units(reorder_max, reorder_qty, on_hand) -> int:
    reorder_max = reorder_max or 0
    on_hand = on_hand or 0
    if reorder_max > 0:
        needed = reorder_max - on_hand
        return max(1, int(needed))
    return max(1, int(reorder_qty or 1))


def carton_note(pack_qty, pack_unit, barcode) -> str:
    pack_qty = pack_qty if pack_qty and pack_qty > 0 else 1
    return f"{pack_qty} × {pack_unit}  |  barcode: {barcode}"


def auto_populate_po_lines(po_id, supplier_id) -> str:
    """
    Populate a new PO with milk-forecast, reorder-point, and auto-reorder lines.
    Returns a banner text string summarising what was added.
    """
    banner_parts = []

    # Milk demand forecast
    milk_recs     = get_milk_order_recommendations(supplier_id)
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


def reload_reorder_recommendations(po_id, supplier_id) -> int | None:
    """
    Add new reorder recommendations to an existing PO.
    Returns None if no products are at reorder point, 0 if all are already on the PO,
    or the positive count of lines added.
    """
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


def lookup_product_for_po(barcode, po_id, supplier_id, unit_mode) -> dict | None:
    """
    Validate a barcode for addition to a PO line and calculate a suggested quantity.

    Returns a dict with product info on success, or None if the barcode is not found.
    Raises ValueError with a structured code on validation failures:
      'already_on_po:{line_num}:{description}' — product is already on this PO
      'not_linked:{supplier_name}'              — product is not linked to the PO supplier
    """
    import models.product as product_model
    import models.product_suppliers as ps_model
    import models.stock_on_hand as stock_model

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
