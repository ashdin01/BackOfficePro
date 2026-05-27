import logging
import models.sales_daily as sales_daily_model
import models.plu_barcode_map as plu_map_model
import models.product as product_model
import models.department as department_model
import models.supplier as supplier_model


# ── PLU map ───────────────────────────────────────────────────────────────────

def ensure_plu_map_table() -> None:
    plu_map_model.ensure_table()


def save_plu_map(plu, barcode: str) -> None:
    """Persist a PLU→barcode mapping and backfill historical movements."""
    try:
        plu_int = int(str(plu).strip())
    except (ValueError, TypeError):
        return
    plu_map_model.save(plu_int, barcode)
    sales_daily_model.backfill_movements(plu, barcode)


def load_plu_map() -> dict:
    """Return {plu_int: barcode} from the persistent map table."""
    return plu_map_model.load()


# ── Reference data ────────────────────────────────────────────────────────────

def get_departments() -> list:
    return department_model.get_all(active_only=True)


def get_suppliers() -> list:
    return supplier_model.get_all(active_only=True)


def barcode_exists(barcode: str) -> bool:
    return product_model.barcode_exists(barcode)


def get_all_products() -> list:
    """All active products with dept/supplier names for the match dialog."""
    return product_model.get_all_with_stock()


# ── Product barcode update ────────────────────────────────────────────────────

def update_product_barcode(old_bc: str, new_bc: str) -> None:
    """Rename a barcode across all referencing tables atomically."""
    product_model.rename_barcode(old_bc, new_bc)


# ── Sales data queries ────────────────────────────────────────────────────────

def sales_table_exists() -> bool:
    return sales_daily_model.table_exists()


def get_sales_groups() -> list:
    """Distinct sub_group values from sales_daily, sorted."""
    return sales_daily_model.get_groups()


def get_sales_stats(d_from: str, d_to: str, group=None) -> dict:
    """
    Aggregate stats for the date range.
    Returns: total_rev, total_qty, total_days, top_name, top_sales.
    """
    return sales_daily_model.get_stats(d_from, d_to, group)


def get_products_with_stock() -> list:
    """All active products joined with dept, supplier, and stock on hand."""
    return product_model.get_all_with_stock()


def get_sales_by_product(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by PLU for the date range.
    Returns list of dicts: plu, plu_name, sub_group, qty, sales, avg_day.
    """
    return sales_daily_model.get_by_product(d_from, d_to, group)


def get_sales_by_day(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by date.
    Returns list of dicts: sale_date, quantity, sales_dollars, discount, net_sales.
    """
    return sales_daily_model.get_by_day(d_from, d_to, group)


def get_sales_by_group(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by sub_group.
    Returns list of dicts: sub_group, quantity, sales_dollars.
    """
    return sales_daily_model.get_by_group(d_from, d_to, group)


def record_pos_sale(reference: str, sale_date: str, operator: str, items: list) -> bool:
    """
    Record a completed POS sale.
    items: list of {barcode, qty, line_total, description} — barcodes are resolved here.
    Returns True if newly recorded, False if this reference was already processed.
    Raises on invalid input or DB error.
    """
    from models.barcode_alias import resolve as _resolve
    import models.stock_on_hand as soh_model

    resolved_items = []
    for item in items:
        barcode = str(item.get('barcode', '')).strip()
        qty     = float(item.get('qty', 0))
        if not barcode or qty <= 0:
            continue
        resolved_items.append({
            'barcode':     _resolve(barcode),
            'qty':         qty,
            'line_total':  float(item.get('line_total', 0)),
            'description': str(item.get('description', '')).strip(),
        })

    return soh_model.record_pos_sale_atomic(reference, sale_date, operator, resolved_items)
