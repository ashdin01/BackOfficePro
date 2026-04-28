import models.supplier as supplier_model
import models.product_suppliers as ps_model


def get_all(active_only=True):
    return supplier_model.get_all(active_only=active_only)


def get_by_id(supplier_id):
    return supplier_model.get_by_id(supplier_id)


def add(code, name, **kwargs):
    supplier_model.add(code, name, **kwargs)


def update(supplier_id, code, name, **kwargs):
    supplier_model.update(supplier_id, code, name, **kwargs)


def deactivate(supplier_id):
    supplier_model.deactivate(supplier_id)


def get_products(supplier_id, default_only=True):
    """Return active products linked to this supplier."""
    return ps_model.get_by_supplier(supplier_id, default_only=default_only)
