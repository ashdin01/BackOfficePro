import models.stock_on_hand as soh_model
import models.product as product_model
import models.supplier as supplier_model
import models.department as department_model
import models.settings as settings_model
import models.report as report_model
from datetime import date, timedelta


def get_stock_valuation() -> list[dict]:
    """Return all active products with current SOH for a stock valuation report."""
    return soh_model.get_all_with_product()


def get_below_reorder() -> list[dict]:
    """Return products whose SOH is at or below their reorder point."""
    return soh_model.get_below_reorder()


def get_all_products(active_only=True) -> list[dict]:
    return product_model.get_all(active_only=active_only)


def get_all_suppliers(active_only=True) -> list[dict]:
    return supplier_model.get_all(active_only=active_only)


def get_all_departments(active_only=True) -> list[dict]:
    return department_model.get_all(active_only=active_only)


def get_setting(key, default='') -> str:
    return settings_model.get_setting(key, default)


# ── Stock Valuation ───────────────────────────────────────────────────────────

def get_stock_valuation_summary(dept_ids=None, as_of_date=None) -> list[dict]:
    """Department summary: product count, total units, cost and sell values.
    as_of_date ('YYYY-MM-DD') reconstructs historical quantities from
    stock_movements; prices used are always today's (no price history kept)."""
    return report_model.get_stock_valuation_summary(dept_ids, as_of_date)


def get_stock_valuation_detail(dept_ids=None, as_of_date=None) -> list[dict]:
    """Full product detail: barcode, description, qty, cost and sell values."""
    return report_model.get_stock_valuation_detail(dept_ids, as_of_date)


# ── Reorder Report ────────────────────────────────────────────────────────────

def get_reorder_items(dept_id=None, supplier_id=None) -> list[dict]:
    """Products at or below reorder point with suggested order quantities."""
    return report_model.get_reorder_items(dept_id, supplier_id)


# ── Movement History ──────────────────────────────────────────────────────────

def get_stock_movements(barcode=None, move_type=None, date_from=None, date_to=None, limit=2000) -> list[dict]:
    """Stock movements with optional filtering by barcode/description, type and date range."""
    return report_model.get_stock_movements(barcode, move_type, date_from, date_to, limit)


# ── GST Report ────────────────────────────────────────────────────────────────

def get_gst_report(date_from, date_to) -> dict:
    """
    GST collected on sales and GST paid on received POs for a date range.
    Returns {'sales': {...}, 'purchases': {...}} matching BAS field names.
    """
    return report_model.get_gst_report(date_from, date_to)


# ── GP Report ─────────────────────────────────────────────────────────────────

def get_gp_data(dept_id=None, gp_filter='all') -> list[dict]:
    """Product-level GP% and GP$ with optional department and tier filtering."""
    return report_model.get_gp_data(dept_id, gp_filter)


def get_gp_summary(dept_id=None) -> list[dict]:
    """Department-level GP summary: avg GP%, healthy/marginal/low counts."""
    return report_model.get_gp_summary(dept_id)


# ── Liquor Tracking ───────────────────────────────────────────────────────────

def get_liquor_tracking(dept_id=None, date_from=None, date_to=None) -> list[dict]:
    """
    SOH start/end and IN/OUT movements per product for a date range.
    Returns rows ordered by group_name, description.
    """
    return report_model.get_liquor_tracking(dept_id, date_from, date_to)


# ── Supplier Sales ────────────────────────────────────────────────────────────

def get_supplier_sales(supplier_id=None) -> tuple[list[dict], list]:
    """
    Per-product sales quantities across 8 time periods.
    Returns (rows, totals) where rows is a list of dicts with keys
    barcode, description, supplier_name, qty (list of 8 ints) and
    totals is a list of 8 column totals.
    """
    return report_model.get_supplier_sales(supplier_id)


# ── Write-off Report ─────────────────────────────────────────────────────────

def get_writeoff_data(date_from, date_to, dept_id=None, category=None) -> list[dict]:
    """Write-off/shrinkage movements for a date range with optional filtering."""
    return report_model.get_writeoff_data(date_from, date_to, dept_id, category)


def get_combined_daily_revenue(d_from, d_to) -> dict:
    """Return {date_str: {'pos': float, 'ar': float}} for the date range."""
    return report_model.get_combined_daily_revenue(d_from, d_to)
