"""Purchase order model wrappers and receipt helpers.

Reorder/forecast logic lives in po_reorder_controller.
PDF/email/CSV export lives in po_export_controller.
Both are re-exported here so existing callers are unaffected.
"""
import models.po_charges as charges_model
import models.po_lines as lines_model
import models.purchase_order as po_model
import models.settings as settings_model

# Re-exports — views import these via po_ctrl without knowing which module owns them
from controllers.po_reorder_controller import (      # noqa: F401
    get_reorder_recommendations,
    get_auto_reorder_items,
    get_items_for_supplier,
    get_sales_for_barcode,
    get_sales_for_barcode_range,
    get_sales_for_barcodes_range,
    get_received_line_count,
    _days_to_next_delivery,
    get_milk_order_recommendations,
    cartons_needed,
    calc_order_units,
    carton_note,
    auto_populate_po_lines,
    reload_reorder_recommendations,
    lookup_product_for_po,
)
from controllers.po_export_controller import (       # noqa: F401
    generate_po_pdf_to_disk,
    send_po_email,
    write_po_csv,
)


# ── Purchase order model wrappers ─────────────────────────────────────────────

def get_po_with_supplier(po_id) -> dict | None:
    """Return the PO row joined with supplier name as a dict, or None."""
    return po_model.get_with_supplier(po_id)


def get_unreceived_lines(po_id) -> list[dict]:
    """Lines where received_qty < ordered_qty. Returns list of dicts."""
    return lines_model.get_unreceived(po_id)


def close_po_force(po_id, unreceived_line_ids, reason) -> None:
    """Mark listed lines NOT SUPPLIED and set PO status to RECEIVED atomically."""
    po_model.close_force(po_id, unreceived_line_ids, reason)


def close_credit_atomic(po_id, po_number, line_receipts) -> None:
    """
    Close a Credit/Return PO atomically.
    line_receipts: list of dicts with line_id, barcode, return_cartons, qty_units.
    SOH is reduced by qty_units for each line; movements are RETURN type.
    """
    po_model.close_credit_atomic(po_id, po_number, line_receipts)


def receive_po_atomic(po_id, po_number, line_receipts, final_status,
                      supplier_invoice_number='', charges=None) -> None:
    """
    Apply a full PO receipt in one atomic transaction.

    line_receipts is a list of dicts:
        line_id, barcode, new_received_qty,
        actual_cost, unit_cost, is_promo,
        qty_units   (number of individual units being received, for SOH)

    Raises on any error; the caller must not catch silently.
    """
    po_model.receive_atomic(po_id, po_number, line_receipts, final_status,
                            supplier_invoice_number=supplier_invoice_number,
                            charges=charges)


def get_all_pos(status=None, archived=False) -> list[dict]:
    return po_model.get_all(status=status, archived=archived)


def get_po_by_id(po_id) -> dict | None:
    return po_model.get_by_id(po_id)


def get_po_by_number(po_number) -> dict | None:
    """Look up a PO by its po_number string (case-insensitive)."""
    return po_model.get_by_po_number(po_number)


def get_receivable_pos() -> list[dict]:
    """Return SENT and PARTIAL POs with line counts — for the mobile receive app."""
    return po_model.get_receivable()


def create_po(supplier_id, delivery_date=None, notes='', created_by='', po_type='PO') -> int:
    return po_model.create(supplier_id, delivery_date=delivery_date,
                           notes=notes, created_by=created_by, po_type=po_type)


def update_po_status(po_id, status) -> None:
    po_model.update_status(po_id, status)


def delete_draft_po(po_id) -> None:
    po_model.cancel(po_id)


def cancel_po(po_id) -> None:
    po_model.cancel(po_id)


def cleanup_old_pos() -> int:
    return po_model.cleanup_old_pos()


def reverse_po(po_id, reversed_by='') -> None:
    po_model.reverse(po_id, reversed_by=reversed_by)


# ── PO lines model wrappers ───────────────────────────────────────────────────

def get_po_lines(po_id) -> list[dict]:
    return lines_model.get_by_po(po_id)


def _validate_po_line_qty_cost(ordered_qty, unit_cost):
    from utils.validators import positive_number
    try:
        if float(ordered_qty) <= 0:
            raise ValueError("Ordered quantity must be greater than zero")
    except (TypeError, ValueError) as e:
        raise ValueError("Ordered quantity must be greater than zero") from e
    positive_number(unit_cost, "Unit cost")


def add_po_line(po_id, barcode, description, ordered_qty, unit_cost=0, notes='', pack_qty=1) -> None:
    _validate_po_line_qty_cost(ordered_qty, unit_cost)
    lines_model.add(po_id, barcode, description, ordered_qty,
                    unit_cost=unit_cost, notes=notes, pack_qty=pack_qty)


def update_po_line(line_id, ordered_qty, unit_cost, notes) -> None:
    _validate_po_line_qty_cost(ordered_qty, unit_cost)
    lines_model.update(line_id, ordered_qty, unit_cost, notes)


def delete_po_line(line_id) -> None:
    lines_model.delete(line_id)


def add_po_note_line(po_id, text) -> None:
    lines_model.add_note(po_id, text)


def renumber_po_lines(po_id, ordered_ids) -> None:
    lines_model.renumber_sort_order(po_id, ordered_ids)


# ── PO charges model wrappers ─────────────────────────────────────────────────

def get_po_charges(po_id) -> list[dict]:
    return charges_model.get_by_po(po_id)


# ── Settings model wrapper ────────────────────────────────────────────────────

def get_setting(key, default='') -> str:
    return settings_model.get_setting(key, default=default)
