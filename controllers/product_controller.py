import logging
from database.connection import get_connection
import models.product as product_model
import models.product_suppliers as ps_model
import models.stock_on_hand as soh_model


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


def get_product_suppliers(barcode, fallback_supplier_id=None,
                          fallback_sku='', fallback_pack_qty=1, fallback_pack_unit='EA'):
    """
    Return supplier entries for a product as a list of dicts:
    {supplier_id, supplier_name, is_default, supplier_sku, pack_qty, pack_unit}
    Falls back to a single-entry list when the junction table has no rows and
    fallback_supplier_id is given (products not yet migrated to v14+).
    """
    rows = ps_model.get_by_barcode(barcode)
    if rows:
        return [
            {'supplier_id':   r['supplier_id'],
             'supplier_name': r['supplier_name'],
             'is_default':    bool(r['is_default']),
             'supplier_sku':  r['supplier_sku'] or '',
             'pack_qty':      int(r['pack_qty']) if r['pack_qty'] else 1,
             'pack_unit':     r['pack_unit'] or 'EA'}
            for r in rows
        ]
    if fallback_supplier_id:
        import models.supplier as _sup_model
        sup = _sup_model.get_by_id(fallback_supplier_id)
        name = sup['name'] if sup else '-- None --'
        return [{'supplier_id': fallback_supplier_id, 'supplier_name': name, 'is_default': True,
                 'supplier_sku': fallback_sku, 'pack_qty': fallback_pack_qty,
                 'pack_unit': fallback_pack_unit}]
    return []


def get_movement_history(barcode, move_type=None):
    """
    Return stock movement rows for a product, newest first.
    Each row: (movement_type, quantity, reference, notes, created_at)
    Optionally filter by a specific movement_type string.
    """
    conn = get_connection()
    try:
        sql = """
            SELECT movement_type, quantity, reference, notes, created_at
            FROM stock_movements
            WHERE barcode = ?
        """
        params = [barcode]
        if move_type and move_type != "ALL":
            sql += " AND movement_type = ?"
            params.append(move_type)
        sql += " ORDER BY created_at ASC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def get_recent_adjustments(limit=100):
    """
    Return the most recent non-sale/receipt stock movements across all products.
    Each row: (created_at, barcode, description, movement_type, quantity, reference, notes)
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT m.created_at, m.barcode, p.description,
                   m.movement_type, m.quantity, m.reference, m.notes
            FROM stock_movements m
            LEFT JOIN products p ON m.barcode = p.barcode
            WHERE m.movement_type NOT IN ('SALE', 'RECEIPT')
            ORDER BY m.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [tuple(r) for r in rows]
    finally:
        conn.close()
