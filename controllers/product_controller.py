import logging
from database.connection import get_connection
import models.product as product_model
import models.product_suppliers as ps_model


def check_barcode_available(barcode):
    """Returns the description of the product using this barcode, or None if free."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT description FROM products WHERE barcode=?", (barcode,)
        ).fetchone()
        return row['description'] if row else None
    finally:
        conn.close()


def rename_barcode(old_bc, new_bc):
    """
    Rename a barcode across all referencing tables atomically.
    Raises ValueError if new_bc is already in use.
    Raises on DB error after rolling back.
    """
    owner = check_barcode_available(new_bc)
    if owner is not None:
        raise ValueError(f"Barcode {new_bc!r} already belongs to: {owner}")

    conn = get_connection()
    try:
        conn.execute("PRAGMA defer_foreign_keys = ON")
        conn.execute("UPDATE products SET barcode=?, updated_at=CURRENT_TIMESTAMP WHERE barcode=?",
                     (new_bc, old_bc))
        conn.execute("UPDATE stock_movements SET barcode=? WHERE barcode=?", (new_bc, old_bc))
        conn.execute("UPDATE stock_on_hand SET barcode=? WHERE barcode=?", (new_bc, old_bc))
        conn.execute("UPDATE po_lines SET barcode=? WHERE barcode=?", (new_bc, old_bc))
        conn.execute("UPDATE product_suppliers SET barcode=? WHERE barcode=?", (new_bc, old_bc))
        conn.execute("UPDATE barcode_aliases SET master_barcode=? WHERE master_barcode=?", (new_bc, old_bc))
        conn.execute("UPDATE barcode_aliases SET alias_barcode=? WHERE alias_barcode=?", (new_bc, old_bc))
        conn.execute("UPDATE plu_barcode_map SET barcode=? WHERE barcode=?", (new_bc, old_bc))
        conn.execute("UPDATE stocktake_counts SET barcode=? WHERE barcode=?", (new_bc, old_bc))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"Barcode rename failed {old_bc!r} → {new_bc!r}: {e}", exc_info=True)
        raise
    finally:
        conn.close()


def get_stock_on_order(barcode):
    """Returns total outstanding units across open POs for a barcode."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM((pl.ordered_qty - pl.received_qty) * "
            "COALESCE(p.pack_qty, 1)), 0) "
            "FROM po_lines pl "
            "JOIN purchase_orders po ON po.id = pl.po_id "
            "JOIN products p ON p.barcode = pl.barcode "
            "WHERE pl.barcode=? AND po.status IN ('DRAFT','SENT','PARTIAL') "
            "AND (pl.ordered_qty - pl.received_qty) > 0",
            (barcode,)
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def save_product(barcode, description, brand, plu, supplier_sku, pack_qty, pack_unit,
                 group_id, department_id, supplier_id, unit, sell_price, cost_price,
                 tax_rate, reorder_point, reorder_max, variable_weight, expected,
                 active, auto_reorder, product_suppliers):
    """
    Save product fields and supplier associations.
    Raises ValueError on validation failure.
    Raises on DB error.
    """
    if not description.strip():
        raise ValueError("Description is required.")

    product_model.update(
        barcode=barcode,
        description=description,
        brand=brand,
        plu=plu,
        supplier_sku=supplier_sku,
        pack_qty=pack_qty,
        pack_unit=pack_unit,
        group_id=group_id,
        department_id=department_id,
        supplier_id=supplier_id,
        unit=unit,
        sell_price=sell_price,
        cost_price=cost_price,
        tax_rate=tax_rate,
        reorder_point=reorder_point,
        reorder_max=reorder_max,
        variable_weight=variable_weight,
        expected=expected,
        active=active,
        auto_reorder=auto_reorder,
    )
    ps_model.save_for_barcode(barcode, product_suppliers)
