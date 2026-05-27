from datetime import date

import models.dashboard as dashboard_model
import models.sales_daily as sales_daily_model


def get_dashboard_stats() -> dict:
    """
    Returns a dict with all stats needed by the home screen:
        store_name, today_sales, open_po_count, low_stock_count, active_product_count
    """
    return dashboard_model.get_stats()


def get_last_import_date() -> date | None:
    """Return the most recent sale_date in sales_daily as a date object, or None."""
    return sales_daily_model.get_last_import_date()
