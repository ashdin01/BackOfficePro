import logging
from database.connection import get_connection


# ── Internal helper ───────────────────────────────────────────────────────────

def _where_params(d_from, d_to, group=None):
    where  = "WHERE sale_date BETWEEN ? AND ?"
    params = [d_from, d_to]
    if group:
        where += " AND sub_group = ?"
        params.append(group)
    return where, params


# ── PLU map ───────────────────────────────────────────────────────────────────

def ensure_plu_map_table():
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
    finally:
        conn.close()


def save_plu_map(plu, barcode: str):
    """Persist a PLU→barcode mapping and backfill historical movements."""
    try:
        plu_int = int(str(plu).strip())
    except (ValueError, TypeError):
        return
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO plu_barcode_map (plu, barcode, mapped_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (plu_int, barcode)
        )
        conn.commit()
    finally:
        conn.close()
    backfill_sale_movements(plu, barcode)


def backfill_sale_movements(plu, barcode: str):
    """Create stock movements for sales_daily rows imported before PLU was mapped."""
    try:
        plu_str = str(plu).strip()
        conn = get_connection()
        try:
            orphaned = conn.execute("""
                SELECT sd.sale_date, sd.plu, sd.plu_name, sd.quantity
                FROM sales_daily sd
                WHERE sd.plu = ?
                AND NOT EXISTS (
                    SELECT 1 FROM stock_movements sm
                    WHERE sm.barcode = ?
                    AND sm.reference = 'SALE-' || sd.sale_date || '-PLU' || sd.plu
                )
                ORDER BY sd.sale_date
            """, (plu_str, barcode)).fetchall()

            if not orphaned:
                return

            backfilled = 0
            for row in orphaned:
                reference = f"SALE-{row['sale_date']}-PLU{row['plu']}"
                quantity  = float(row['quantity'])
                plu_name  = row['plu_name'] or ""

                conn.execute("""
                    INSERT INTO stock_movements
                        (barcode, movement_type, quantity, reference, notes, created_by)
                    VALUES (?, 'SALE', ?, ?, ?, 'PDF Import (backfill)')
                """, (barcode, -quantity, reference,
                      f"Backfill: {plu_name} ({quantity} units)"))

                conn.execute("""
                    INSERT INTO stock_on_hand (barcode, quantity)
                    VALUES (?, ?)
                    ON CONFLICT(barcode) DO UPDATE SET
                        quantity = quantity + excluded.quantity,
                        last_updated = CURRENT_TIMESTAMP
                """, (barcode, -quantity))

                backfilled += 1

            conn.commit()
            if backfilled:
                logging.info("Backfilled %d sale movements for PLU %s → %s",
                             backfilled, plu, barcode)
        finally:
            conn.close()
    except Exception as e:
        logging.warning("Sales backfill error: %s", e, exc_info=True)


def load_plu_map() -> dict:
    """Return {plu_int: barcode} from the persistent map table."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT plu, barcode FROM plu_barcode_map").fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}
    finally:
        conn.close()


# ── Reference data ────────────────────────────────────────────────────────────

def get_departments() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name FROM departments WHERE active=1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_suppliers() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name FROM suppliers WHERE active=1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def barcode_exists(barcode: str) -> bool:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT 1 FROM products WHERE barcode=?", (barcode,)
        ).fetchone() is not None
    finally:
        conn.close()


def get_all_products() -> list:
    """All active products with dept/supplier names for the match dialog."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.barcode, p.description, p.brand,
                   COALESCE(p.plu, '') as plu,
                   d.name as dept_name, d.id as dept_id,
                   s.name as supplier_name, s.id as supplier_id,
                   p.sell_price, p.cost_price, p.unit
            FROM products p
            LEFT JOIN departments d ON p.department_id = d.id
            LEFT JOIN suppliers   s ON p.supplier_id   = s.id
            WHERE p.active = 1
            ORDER BY p.description
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Product barcode update ────────────────────────────────────────────────────

def update_product_barcode(old_bc: str, new_bc: str):
    """Copy the product row to a new barcode, transfer SOH, delete the old row."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO products
                (barcode,base_sku,description,department_id,supplier_id,
                 brand,unit,unit_size,units_per_carton,sell_price,cost_price,
                 carton_price,tax_rate,reorder_point,variable_weight,
                 expected,active,notes,created_at,updated_at)
            SELECT ?,base_sku,description,department_id,supplier_id,
                 brand,unit,unit_size,units_per_carton,sell_price,cost_price,
                 carton_price,tax_rate,reorder_point,variable_weight,
                 expected,active,notes,created_at,CURRENT_TIMESTAMP
            FROM products WHERE barcode=?
        """, (new_bc, old_bc))
        conn.execute("""
            INSERT OR IGNORE INTO stock_on_hand (barcode,quantity)
            SELECT ?,quantity FROM stock_on_hand WHERE barcode=?
        """, (new_bc, old_bc))
        conn.execute("DELETE FROM stock_on_hand WHERE barcode=?", (old_bc,))
        conn.execute("DELETE FROM products WHERE barcode=?", (old_bc,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Sales data queries ────────────────────────────────────────────────────────

def sales_table_exists() -> bool:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sales_daily'"
        ).fetchone() is not None
    finally:
        conn.close()


def get_sales_groups() -> list:
    """Distinct sub_group values from sales_daily, sorted."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT sub_group FROM sales_daily "
            "WHERE sub_group IS NOT NULL ORDER BY sub_group"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_sales_stats(d_from: str, d_to: str, group=None) -> dict:
    """
    Aggregate stats for the date range.
    Returns: total_rev, total_qty, total_days, top_name, top_sales.
    """
    where, params = _where_params(d_from, d_to, group)
    conn = get_connection()
    try:
        stats = conn.execute(f"""
            SELECT SUM(sales_dollars) + SUM(discount), SUM(quantity),
                   COUNT(DISTINCT sale_date)
            FROM sales_daily {where}
        """, params).fetchone()
        top = conn.execute(f"""
            SELECT plu_name, SUM(sales_dollars) AS s
            FROM sales_daily {where}
            GROUP BY plu ORDER BY s DESC LIMIT 1
        """, params).fetchone()
        return {
            'total_rev':   stats[0] or 0,
            'total_qty':   stats[1] or 0,
            'total_days':  stats[2] or 0,
            'top_name':    top[0][:30] if top else None,
            'top_sales':   top[1]      if top else None,
        }
    finally:
        conn.close()


def get_products_with_stock() -> list:
    """All active products joined with dept, supplier, and stock on hand."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.barcode, p.plu, p.description, p.brand,
                   d.name  AS dept_name,
                   s.name  AS supplier_name,
                   p.unit, p.sell_price, p.cost_price,
                   COALESCE(soh.quantity, 0) AS on_hand
            FROM products p
            LEFT JOIN departments   d   ON p.department_id = d.id
            LEFT JOIN suppliers     s   ON p.supplier_id   = s.id
            LEFT JOIN stock_on_hand soh ON soh.barcode     = p.barcode
            WHERE p.active = 1
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sales_by_product(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by PLU for the date range.
    Returns list of dicts: plu, plu_name, sub_group, qty, sales, avg_day.
    """
    where, params = _where_params(d_from, d_to, group)
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT
                sd.plu,
                sd.plu_name,
                sd.sub_group,
                SUM(sd.quantity)      AS qty,
                SUM(sd.sales_dollars) AS sales,
                SUM(sd.sales_dollars) / NULLIF(COUNT(DISTINCT sd.sale_date), 0) AS avg_day
            FROM sales_daily sd
            {where}
            GROUP BY sd.plu
            ORDER BY sales DESC
        """, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sales_by_day(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by date.
    Returns list of dicts: sale_date, quantity, sales_dollars, discount, net_sales.
    """
    where, params = _where_params(d_from, d_to, group)
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT sale_date,
                   SUM(quantity)      AS quantity,
                   SUM(sales_dollars) AS sales_dollars,
                   SUM(discount)      AS discount,
                   SUM(sales_dollars) + SUM(discount) AS net_sales
            FROM sales_daily {where}
            GROUP BY sale_date ORDER BY sale_date DESC
        """, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sales_by_group(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by sub_group.
    Returns list of dicts: sub_group, quantity, sales_dollars.
    """
    where, params = _where_params(d_from, d_to, group)
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT sub_group,
                   SUM(quantity)      AS quantity,
                   SUM(sales_dollars) AS sales_dollars
            FROM sales_daily {where}
            GROUP BY sub_group ORDER BY SUM(sales_dollars) DESC
        """, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
