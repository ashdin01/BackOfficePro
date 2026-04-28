import models.stock_on_hand as soh_model
import models.product as product_model
import models.supplier as supplier_model
import models.department as department_model
import models.settings as settings_model


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
