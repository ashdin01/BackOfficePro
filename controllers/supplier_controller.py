import models.supplier as supplier_model
import models.product_suppliers as ps_model


def get_all(active_only=True) -> list[dict]:
    return supplier_model.get_all(active_only=active_only)


def get_by_id(supplier_id) -> dict | None:
    return supplier_model.get_by_id(supplier_id)


def create(code, name, *, contact_name='', phone='', account_number='',
           payment_terms='', address='', notes='', abn='', rep_name='', rep_phone='',
           order_minimum=0, email_orders='', email_admin='', email_accounts='', email_rep='',
           online_order=0, online_order_note='', order_days='',
           order_first_monday=0, order_fortnightly_start='', delivery_days='',
           bank_account_name='', bank_bsb='', bank_account_number='') -> None:
    # All params after code/name are keyword-only (the * enforces this).
    # Passing them positionally raises TypeError immediately — don't remove the *.
    supplier_model.create(
        code, name,
        contact_name=contact_name, phone=phone, account_number=account_number,
        payment_terms=payment_terms, address=address, notes=notes, abn=abn,
        rep_name=rep_name, rep_phone=rep_phone, order_minimum=order_minimum,
        email_orders=email_orders, email_admin=email_admin, email_accounts=email_accounts,
        email_rep=email_rep, online_order=online_order, online_order_note=online_order_note,
        order_days=order_days, order_first_monday=order_first_monday,
        order_fortnightly_start=order_fortnightly_start, delivery_days=delivery_days,
        bank_account_name=bank_account_name, bank_bsb=bank_bsb,
        bank_account_number=bank_account_number,
    )


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
