import models.supplier as supplier_model
import models.product_suppliers as ps_model


def get_all(active_only=True) -> list[dict]:
    return supplier_model.get_all(active_only=active_only)


def get_by_id(supplier_id) -> dict | None:
    return supplier_model.get_by_id(supplier_id)


def create(code, name, **kwargs) -> None:
    supplier_model.create(code, name, **kwargs)


def update(supplier_id, code, name, contact_name='', phone='', account_number='',
           payment_terms='', address='', notes='', active=1, **kwargs) -> None:
    supplier_model.update(
        supplier_id, code, name, contact_name, phone, account_number,
        payment_terms, address, notes, active, **kwargs
    )


def deactivate(supplier_id) -> None:
    supplier_model.deactivate(supplier_id)


def get_products(supplier_id, default_only=True) -> list[dict]:
    """Return active products linked to this supplier."""
    return ps_model.get_by_supplier(supplier_id, default_only=default_only)


def get_order_due_today() -> list[dict]:
    return supplier_model.get_order_due_today()
