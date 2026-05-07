import models.stock_on_hand as soh_model
import models.product as product_model
import models.supplier as supplier_model
import models.department as department_model
import models.settings as settings_model
from database.connection import get_connection
from datetime import date, timedelta


def get_stock_valuation():
    """Return all active products with current SOH for a stock valuation report."""
    return soh_model.get_all_with_product()


def get_below_reorder():
    """Return products whose SOH is at or below their reorder point."""
    return soh_model.get_below_reorder()


def get_all_products(active_only=True):
    return product_model.get_all(active_only=active_only)


def get_all_suppliers(active_only=True):
    return supplier_model.get_all(active_only=active_only)


def get_all_departments(active_only=True):
    return department_model.get_all(active_only=active_only)


def get_setting(key, default=''):
    return settings_model.get_setting(key, default)


# ── Stock Valuation ───────────────────────────────────────────────────────────

def get_stock_valuation_summary(dept_id=None):
    """Department summary: product count, total units, cost and sell values."""
    conn = get_connection()
    sql = """
        SELECT d.name as dept_name,
               COUNT(p.barcode) as product_count,
               SUM(COALESCE(s.quantity,0)) as total_units,
               SUM(COALESCE(s.quantity,0) * p.cost_price) as cost_value,
               SUM(COALESCE(s.quantity,0) * p.sell_price) as sell_value
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    sql += " GROUP BY d.name ORDER BY d.name"
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def get_stock_valuation_detail(dept_id=None):
    """Full product detail: barcode, description, qty, cost and sell values."""
    conn = get_connection()
    sql = """
        SELECT p.barcode, p.description, d.name as dept_name,
               p.unit, p.cost_price, p.sell_price,
               COALESCE(s.quantity,0) as quantity,
               COALESCE(s.quantity,0) * p.cost_price as cost_value,
               COALESCE(s.quantity,0) * p.sell_price as sell_value
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    sql += " ORDER BY d.name, p.description"
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ── Reorder Report ────────────────────────────────────────────────────────────

def get_reorder_items(dept_id=None, supplier_id=None):
    """Products at or below reorder point with suggested order quantities."""
    conn = get_connection()
    sql = """
        SELECT p.barcode, p.description, d.name as dept_name,
               sup.name as supplier_name,
               COALESCE(s.quantity, 0) as on_hand,
               p.reorder_point,
               COALESCE(p.reorder_max, 0) as reorder_max,
               p.unit, p.cost_price,
               CASE
                   WHEN COALESCE(p.reorder_max, 0) > 0
                   THEN MAX(1, COALESCE(p.reorder_max, 0) - COALESCE(s.quantity, 0))
                   ELSE 0
               END as suggested_qty,
               CASE
                   WHEN COALESCE(p.reorder_max, 0) > 0
                   THEN MAX(1, COALESCE(p.reorder_max, 0) - COALESCE(s.quantity, 0)) * p.cost_price
                   ELSE 0
               END as order_cost
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        LEFT JOIN departments d ON p.department_id = d.id
        LEFT JOIN suppliers sup ON p.supplier_id = sup.id
        WHERE p.active = 1
          AND COALESCE(s.quantity, 0) <= p.reorder_point
          AND p.reorder_point > 0
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    if supplier_id:
        sql += " AND p.supplier_id = ?"
        params.append(supplier_id)
    sql += " ORDER BY sup.name, d.name, p.description"
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ── Movement History ──────────────────────────────────────────────────────────

def get_stock_movements(barcode=None, move_type=None, date_from=None, date_to=None, limit=2000):
    """Stock movements with optional filtering by barcode/description, type and date range."""
    conn = get_connection()
    sql = """
        SELECT sm.id, sm.barcode, p.description, sm.movement_type,
               sm.quantity, sm.reference, sm.notes, sm.created_at
        FROM stock_movements sm
        LEFT JOIN products p ON sm.barcode = p.barcode
        WHERE 1=1
    """
    params = []
    if barcode:
        sql += " AND (sm.barcode LIKE ? OR p.description LIKE ?)"
        params.extend([f"%{barcode}%", f"%{barcode}%"])
    if move_type and move_type != "ALL":
        sql += " AND sm.movement_type = ?"
        params.append(move_type)
    if date_from:
        sql += " AND date(sm.created_at) >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date(sm.created_at) <= ?"
        params.append(date_to)
    sql += f" ORDER BY sm.created_at DESC LIMIT {int(limit)}"
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ── GST Report ────────────────────────────────────────────────────────────────

def get_gst_report(date_from, date_to) -> dict:
    """
    GST collected on sales and GST paid on received POs for a date range.
    Returns {'sales': {...}, 'purchases': {...}} matching BAS field names.
    """
    conn = get_connection()
    try:
        sales     = _gst_collected(conn, date_from, date_to)
        purchases = _gst_paid(conn, date_from, date_to)
    finally:
        conn.close()
    return {'sales': sales, 'purchases': purchases}


def _gst_collected(conn, d_from, d_to) -> dict:
    rows = conn.execute("""
        SELECT sd.sales_dollars, COALESCE(p.tax_rate, 0) AS tax_rate
        FROM sales_daily sd
        LEFT JOIN plu_barcode_map pbm ON CAST(sd.plu AS TEXT) = CAST(pbm.plu AS TEXT)
        LEFT JOIN products p ON pbm.barcode = p.barcode
        WHERE sd.sale_date BETWEEN ? AND ?
          AND sd.sales_dollars > 0
    """, (str(d_from), str(d_to))).fetchall()

    taxable_sales = exempt_sales = gst_collected = 0.0
    for row in rows:
        dollars  = float(row['sales_dollars'])
        tax_rate = float(row['tax_rate']) if row['tax_rate'] else 0.0
        if tax_rate > 0:
            taxable_sales += dollars
            gst_collected += dollars / (1 + tax_rate / 100) * (tax_rate / 100)
        else:
            exempt_sales += dollars
    return {
        'taxable_sales': round(taxable_sales, 2),
        'exempt_sales':  round(exempt_sales,  2),
        'total_sales':   round(taxable_sales + exempt_sales, 2),
        'gst_collected': round(gst_collected, 2),
        'sales_ex_gst':  round(taxable_sales - gst_collected, 2),
    }


def _gst_paid(conn, d_from, d_to) -> dict:
    rows = conn.execute("""
        SELECT pol.ordered_qty, pol.unit_cost,
               COALESCE(p.tax_rate, 0) AS tax_rate,
               COALESCE(p.pack_qty, 1) AS pack_qty
        FROM po_lines pol
        JOIN purchase_orders po ON po.id = pol.po_id
        LEFT JOIN products p    ON p.barcode = pol.barcode
        WHERE po.status = 'RECEIVED'
          AND DATE(po.received_at) BETWEEN ? AND ?
    """, (str(d_from), str(d_to))).fetchall()

    taxable_purchases = exempt_purchases = gst_paid = 0.0
    for row in rows:
        line_total = (int(row['ordered_qty'] or 0)
                      * int(row['pack_qty'] or 1)
                      * float(row['unit_cost'] or 0))
        tax_rate = float(row['tax_rate'] or 0)
        if tax_rate > 0:
            taxable_purchases += line_total
            gst_paid += line_total / (1 + tax_rate / 100) * (tax_rate / 100)
        else:
            exempt_purchases += line_total
    return {
        'taxable_purchases': round(taxable_purchases, 2),
        'exempt_purchases':  round(exempt_purchases,  2),
        'total_purchases':   round(taxable_purchases + exempt_purchases, 2),
        'gst_paid':          round(gst_paid, 2),
        'purchases_ex_gst':  round(taxable_purchases - gst_paid, 2),
    }


# ── GP Report ─────────────────────────────────────────────────────────────────

def get_gp_data(dept_id=None, gp_filter='all'):
    """Product-level GP% and GP$ with optional department and tier filtering."""
    conn = get_connection()
    sql = """
        SELECT p.barcode, p.description, d.name as dept_name,
               p.sell_price, p.cost_price,
               CASE WHEN p.sell_price > 0
                    THEN ROUND((1.0 - (p.cost_price * (1 + p.tax_rate / 100.0)) / p.sell_price) * 100, 1)
                    ELSE 0 END as gp_pct,
               p.sell_price - (p.cost_price * (1 + p.tax_rate / 100.0)) as gp_dollars
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1 AND p.sell_price > 0
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    if gp_filter == "healthy":
        sql += " AND (1.0 - p.cost_price / p.sell_price) * 100 >= 30"
    elif gp_filter == "marginal":
        sql += " AND (1.0 - p.cost_price / p.sell_price) * 100 >= 15 AND (1.0 - p.cost_price / p.sell_price) * 100 < 30"
    elif gp_filter == "low":
        sql += " AND (1.0 - p.cost_price / p.sell_price) * 100 < 15"
    sql += " ORDER BY gp_pct ASC"
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def get_gp_summary(dept_id=None):
    """Department-level GP summary: avg GP%, healthy/marginal/low counts."""
    conn = get_connection()
    sql = """
        SELECT d.name as dept_name,
               COUNT(*) as product_count,
               ROUND(AVG(CASE WHEN p.sell_price > 0
                    THEN (1.0 - p.cost_price / p.sell_price) * 100
                    ELSE 0 END), 1) as avg_gp,
               SUM(CASE WHEN (1.0 - p.cost_price/p.sell_price)*100 >= 30 THEN 1 ELSE 0 END) as healthy,
               SUM(CASE WHEN (1.0 - p.cost_price/p.sell_price)*100 >= 15
                         AND (1.0 - p.cost_price/p.sell_price)*100 < 30 THEN 1 ELSE 0 END) as marginal,
               SUM(CASE WHEN (1.0 - p.cost_price/p.sell_price)*100 < 15 THEN 1 ELSE 0 END) as low_gp
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1 AND p.sell_price > 0
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    sql += " GROUP BY d.name ORDER BY avg_gp ASC"
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ── Liquor Tracking ───────────────────────────────────────────────────────────

def get_liquor_tracking(dept_id=None, date_from=None, date_to=None):
    """
    SOH start/end and IN/OUT movements per product for a date range.
    Returns rows ordered by group_name, description.
    """
    conn = get_connection()
    try:
        where  = "p.active = 1"
        params = [date_to, date_from, date_to]
        if dept_id is not None:
            where += " AND p.department_id = ?"
            params.append(dept_id)

        return conn.execute(f"""
            SELECT
                p.barcode,
                p.description,
                COALESCE(p.unit, 'EA')                   AS unit,
                COALESCE(g.name, '(No Group)')           AS group_name,
                COALESCE(soh.quantity, 0)                AS current_soh,
                COALESCE(after_end.qty,    0)            AS after_end_net,
                COALESCE(in_per.qty_in,    0)            AS period_in,
                COALESCE(in_per.qty_out,   0)            AS period_out,
                COALESCE(in_per.net,       0)            AS period_net
            FROM products p
            LEFT JOIN product_groups g    ON p.group_id      = g.id
            LEFT JOIN stock_on_hand  soh  ON soh.barcode     = p.barcode
            LEFT JOIN (
                SELECT barcode, SUM(quantity) AS qty
                FROM stock_movements
                WHERE date(created_at) > ?
                GROUP BY barcode
            ) after_end ON after_end.barcode = p.barcode
            LEFT JOIN (
                SELECT barcode,
                    SUM(CASE WHEN quantity > 0 THEN  quantity  ELSE 0 END) AS qty_in,
                    SUM(CASE WHEN quantity < 0 THEN -quantity  ELSE 0 END) AS qty_out,
                    SUM(quantity)                                           AS net
                FROM stock_movements
                WHERE date(created_at) BETWEEN ? AND ?
                GROUP BY barcode
            ) in_per ON in_per.barcode = p.barcode
            WHERE {where}
            ORDER BY group_name, p.description
        """, params).fetchall()
    finally:
        conn.close()


# ── Supplier Sales ────────────────────────────────────────────────────────────

def get_supplier_sales(supplier_id=None):
    """
    Per-product sales quantities across 8 time periods.
    Returns (rows, totals) where rows is a list of dicts with keys
    barcode, description, supplier_name, qty (list of 8 ints) and
    totals is a list of 8 column totals.

    Periods: this week, last week, 2 weeks ago, this month,
             last month, this FY, prior FY, all time.
    """
    today        = date.today()
    lw_s, lw_e   = _week_bounds(0)
    tw_s, tw_e   = _week_bounds(1)
    thisw_s      = today - timedelta(days=today.weekday())
    fy_s,  fy_e  = _fy_bounds()
    pfy_year     = (today.year if today.month >= 7 else today.year - 1) - 1
    pfy_s, pfy_e = _fy_bounds(pfy_year)
    tm_s         = today.replace(day=1)
    lm_e         = tm_s - timedelta(days=1)
    lm_s         = lm_e.replace(day=1)

    conn = get_connection()
    try:
        sup_filter = "AND p.supplier_id = ?" if supplier_id else ""
        sup_params = [supplier_id] if supplier_id else []

        db_rows = conn.execute(f"""
            SELECT p.barcode, p.description, s.name AS supplier_name,
                   COALESCE(pbm.plu, '') AS plu
            FROM products p
            JOIN suppliers s ON s.id = p.supplier_id
            LEFT JOIN plu_barcode_map pbm ON pbm.barcode = p.barcode
            WHERE p.active = 1
              {sup_filter}
            ORDER BY s.name, p.description
        """, sup_params).fetchall()

        # Fetch all sales rows for relevant PLUs in one query, aggregate in Python
        all_plus = [str(r['plu']) for r in db_rows if r['plu']]
        sales_by_plu: dict = {}
        if all_plus:
            placeholders = ','.join('?' * len(all_plus))
            raw = conn.execute(f"""
                SELECT plu, sale_date, quantity FROM sales_daily
                WHERE plu IN ({placeholders})
            """, all_plus).fetchall()
            for sr in raw:
                sales_by_plu.setdefault(sr['plu'], []).append(
                    (sr['sale_date'], sr['quantity'])
                )

        periods = [
            (str(thisw_s),        str(today)),
            (str(lw_s),           str(lw_e)),
            (str(tw_s),           str(tw_e)),
            (str(tm_s),           str(today)),
            (str(lm_s),           str(lm_e)),
            (str(fy_s),           str(fy_e)),
            (str(pfy_s),          str(pfy_e)),
            ('2000-01-01',        str(today)),
        ]

        def qty_from_cache(plu, d1, d2):
            return int(sum(
                q for sd, q in sales_by_plu.get(plu, [])
                if d1 <= sd <= d2
            ))

        rows   = []
        totals = [0] * 8
        for row in db_rows:
            plu = str(row['plu']) if row['plu'] else None
            vals = [qty_from_cache(plu, d1, d2) for d1, d2 in periods] if plu else [0] * 8
            for i, v in enumerate(vals):
                totals[i] += v
            rows.append({
                'barcode':       row['barcode'],
                'description':   row['description'],
                'supplier_name': row['supplier_name'],
                'qty':           vals,
            })
    finally:
        conn.close()

    return rows, totals


# ── Write-off Report ─────────────────────────────────────────────────────────

_SPOILAGE_TYPES  = ['OD - Out of Date']
_SHRINKAGE_TYPES = ['IS - Incorrectly Sold', 'NS - Not on Shelf', 'DG', 'SE - Stocktake Error']
_ADMIN_TYPES     = ['IE - Invoice Error']
_ALL_WRITEOFF    = _SPOILAGE_TYPES + _SHRINKAGE_TYPES + _ADMIN_TYPES


def get_writeoff_data(date_from, date_to, dept_id=None, category=None):
    """Write-off/shrinkage movements for a date range with optional filtering."""
    conn = get_connection()
    placeholders = ','.join('?' for _ in _ALL_WRITEOFF)
    sql = f"""
        SELECT sm.id, sm.barcode, sm.movement_type, sm.quantity,
               sm.notes, sm.created_at, sm.created_by,
               p.description, p.cost_price,
               d.name as dept_name, s.name as supplier_name
        FROM stock_movements sm
        LEFT JOIN products p ON p.barcode = sm.barcode
        LEFT JOIN departments d ON d.id = p.department_id
        LEFT JOIN suppliers s ON s.id = p.supplier_id
        WHERE sm.movement_type IN ({placeholders})
          AND DATE(sm.created_at) BETWEEN ? AND ?
          AND sm.quantity < 0
    """
    params = list(_ALL_WRITEOFF) + [str(date_from), str(date_to)]
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    if category == 'Spoilage':
        ph = ','.join('?' for _ in _SPOILAGE_TYPES)
        sql += f" AND sm.movement_type IN ({ph})"
        params += _SPOILAGE_TYPES
    elif category == 'Shrinkage':
        ph = ','.join('?' for _ in _SHRINKAGE_TYPES)
        sql += f" AND sm.movement_type IN ({ph})"
        params += _SHRINKAGE_TYPES
    elif category == 'Admin':
        ph = ','.join('?' for _ in _ADMIN_TYPES)
        sql += f" AND sm.movement_type IN ({ph})"
        params += _ADMIN_TYPES
    sql += " ORDER BY sm.created_at DESC"
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ── Date utilities (used internally by supplier sales and GST) ────────────────

def _week_bounds(offset=0):
    today = date.today()
    mon   = today - timedelta(days=today.weekday())
    start = mon - timedelta(weeks=(1 + offset))
    return start, start + timedelta(days=6)


def _fy_bounds(year=None):
    today = date.today()
    if year is None:
        year = today.year if today.month >= 7 else today.year - 1
    return date(year, 7, 1), date(year + 1, 6, 30)
