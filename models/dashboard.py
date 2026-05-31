"""Model for dashboard statistics."""
from datetime import date
from database.connection import db_conn


def get_stats() -> dict:
    """
    Returns a dict with all stats needed by the home screen:
        store_name, today_sales, open_po_count, low_stock_count, active_product_count
    """
    with db_conn() as conn:
        today = date.today().isoformat()

        row = conn.execute(
            "SELECT value FROM settings WHERE key='store_name'"
        ).fetchone()
        store_name = row[0] if row and row[0] else "My Supermarket"

        sales = conn.execute(
            "SELECT COALESCE(SUM(sales_dollars), 0) FROM sales_daily WHERE sale_date=?",
            (today,)
        ).fetchone()
        today_sales = float(sales[0] or 0)

        pos = conn.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE status IN ('DRAFT','SENT')"
        ).fetchone()
        open_po_count = int(pos[0] or 0)

        low = conn.execute("""
            SELECT COUNT(*) FROM products p
            LEFT JOIN stock_on_hand s ON s.barcode = p.barcode
            WHERE p.active = 1
              AND p.reorder_point > 0
              AND COALESCE(s.quantity, 0) <= p.reorder_point
        """).fetchone()
        low_stock_count = int(low[0] or 0)

        prods = conn.execute(
            "SELECT COUNT(*) FROM products WHERE active=1"
        ).fetchone()
        active_product_count = int(prods[0] or 0)

        return {
            'store_name':           store_name,
            'today_sales':          today_sales,
            'open_po_count':        open_po_count,
            'low_stock_count':      low_stock_count,
            'active_product_count': active_product_count,
        }
