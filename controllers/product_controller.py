import logging
import os
import models.product as product_model
import models.product_plu as product_plu_model
import models.product_queries as product_queries_model
import models.product_suppliers as ps_model
import models.stock_on_hand as soh_model
import models.barcode_alias as alias_model
import models.plu_barcode_map as plu_map_model
import models.product_selling_units as selling_units_model
import models.stock_movements as movements_model
import models.po_lines as po_lines_model
import models.sales_daily as sales_daily_model


def update_cost_price(barcode, cost) -> None:
    """Update the cost_price on the product master record."""
    product_model.update_cost_price(barcode, cost)


def get_selling_unit_master(barcode) -> dict | None:
    """
    If barcode is an active selling unit, return a dict with master_barcode,
    master_desc, label, unit_qty. Returns None if it is not a selling unit.
    """
    return selling_units_model.get_master(barcode)


def check_barcode_available(barcode) -> str | None:
    """Returns the description of the product using this barcode, or None if free."""
    return product_model.check_barcode_available(barcode)


def rename_barcode(old_bc, new_bc) -> None:
    """
    Rename a barcode across all referencing tables atomically.
    Raises ValueError if new_bc is already in use.
    Raises on DB error after rolling back.
    """
    product_model.rename_barcode(old_bc, new_bc)


def get_stock_on_order(barcode) -> float:
    """Returns total outstanding units across open POs for a barcode."""
    return po_lines_model.get_on_order_total(barcode)


def get_volume_sold(barcode) -> dict | None:
    """
    Weight sold in kg for a variable-weight product (last_week, two_weeks,
    this_month, ytd). Returns None if the product has no PLU mapping.
    """
    return sales_daily_model.get_weight_for_barcode(barcode)


def get_stock_on_order_detail(barcode) -> list[dict]:
    """Returns per-PO breakdown of outstanding units for a barcode."""
    return po_lines_model.get_on_order_detail(barcode)


def save_product(barcode, description, brand, plu, supplier_sku, pack_qty, pack_unit,
                 group_id, department_id, supplier_id, unit, sell_price, cost_price,
                 tax_rate, reorder_point, reorder_max, variable_weight, expected,
                 active, auto_reorder, product_suppliers, online_available=0,
                 online_notes='') -> None:
    """
    Save product fields and supplier associations.
    Raises ValueError on validation failure.
    Raises on DB error.
    """
    from utils.validators import positive_number, percentage
    if not description.strip():
        raise ValueError("Description is required.")
    positive_number(sell_price,   "Sell price")
    positive_number(cost_price,   "Cost price")
    percentage(tax_rate,          "Tax rate")
    positive_number(reorder_point, "Reorder point")
    positive_number(reorder_max,   "Reorder max")

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
        online_available=online_available,
        online_notes=online_notes,
    )
    ps_model.save_for_barcode(barcode, product_suppliers)


def set_online_available(barcode: str, value: bool) -> None:
    product_model.set_online_available(barcode, int(value))


def get_product_suppliers(barcode, fallback_supplier_id=None,
                          fallback_sku='', fallback_pack_qty=1, fallback_pack_unit='EA') -> list[dict]:
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


def get_movement_history(barcode, move_type=None) -> list[dict]:
    """
    Return stock movement rows for a product, newest first.
    Each row: (movement_type, quantity, reference, notes, created_at)
    Optionally filter by a specific movement_type string.
    """
    return movements_model.get_by_barcode(barcode, move_type)


def get_all_plu_products() -> list[dict]:
    """All products that have a PLU assigned, ordered by PLU numerically then barcode."""
    return product_plu_model.get_all_plu()


def get_duplicate_plu_groups() -> list[dict]:
    """
    Returns a list of dicts for every product sharing a PLU with at least one other product.
    Rows are grouped by PLU; within a group products are sorted by active desc then barcode.
    """
    return product_plu_model.get_duplicate_plu_groups()


def get_plu_map_conflicts() -> list[dict]:
    """
    Barcodes where plu_barcode_map.plu differs from products.plu.
    Returns list of dicts with keys: map_plu, barcode, prod_plu, description.
    """
    return product_plu_model.get_plu_map_conflicts()


def set_product_plu(barcode, new_plu) -> None:
    """
    Assign a PLU to a product. new_plu may be a string or int; pass '' or None to clear.
    Raises ValueError if new_plu is already used by a different product.
    """
    product_plu_model.set_plu(barcode, new_plu)


def delete_plu_map_entry(plu) -> None:
    """Delete a single plu_barcode_map row by PLU number (leaves the product record untouched)."""
    plu_map_model.delete(plu)


def sync_plu_map(barcode, plu) -> None:
    """
    Upsert plu_barcode_map so the map entry matches the products.plu value.
    Pass plu=None or '' to remove the map entry.
    """
    plu_map_model.sync(barcode, plu)


def get_selling_units(master_barcode) -> list[dict]:
    """All selling units for a product, ordered by unit_qty. Returns list of dicts."""
    return selling_units_model.get_by_master(master_barcode)


def get_selling_unit_by_id(su_id) -> dict | None:
    """Single selling unit row as a dict, or None."""
    return selling_units_model.get_by_id(su_id)


def add_selling_unit(master_barcode, barcode, plu, label, unit_qty, sell_price) -> None:
    """Insert a new selling unit row."""
    selling_units_model.add(master_barcode, barcode, plu, label, unit_qty, sell_price)


def update_selling_unit(su_id, label, unit_qty, plu, barcode, sell_price) -> None:
    """Update label, qty, PLU, barcode and price on a selling unit row."""
    selling_units_model.update(su_id, label, unit_qty, plu, barcode, sell_price)


def delete_selling_unit(su_id) -> None:
    """Delete a selling unit row by id."""
    selling_units_model.delete(su_id)


def get_recent_adjustments(limit=100) -> list[dict]:
    """
    Return the most recent non-sale/receipt stock movements across all products.
    Each row: (created_at, barcode, description, movement_type, quantity, reference, notes)
    """
    return movements_model.get_recent_adjustments(limit)


# ── GP calculation ────────────────────────────────────────────────────────────

def calculate_gross_profit(sell_price, cost_price, tax_rate) -> float | None:
    """Return gross profit as a percentage of sell price, or None if sell_price is zero."""
    from utils.calculations import gross_profit_pct
    return gross_profit_pct(sell_price, cost_price, tax_rate)


# ── Product image helpers ─────────────────────────────────────────────────────

def find_product_image(barcode) -> str | None:
    """Return the path to an existing product image file, or None."""
    from config.settings import DATA_DIR
    img_dir = os.path.join(DATA_DIR, 'images')
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        p = os.path.join(img_dir, f"{barcode}.{ext}")
        if os.path.exists(p):
            return p
    return None


def prepare_image_destination(barcode) -> str:
    """
    Create the images directory, remove any alternate-extension copies of the
    product image, and return the canonical .jpg destination path.
    """
    from config.settings import DATA_DIR
    img_dir = os.path.join(DATA_DIR, 'images')
    os.makedirs(img_dir, exist_ok=True)
    for ext in ('jpeg', 'png', 'webp', 'bmp'):
        old = os.path.join(img_dir, f"{barcode}.{ext}")
        if os.path.exists(old):
            os.remove(old)
    return os.path.join(img_dir, f"{barcode}.jpg")


def delete_product_image(barcode) -> None:
    """Delete the product image file if one exists."""
    path = find_product_image(barcode)
    if path:
        os.remove(path)


# ── Product model wrappers ────────────────────────────────────────────────────

def get_all_products(active_only=True, include_nonzero_inactive=False) -> list[dict]:
    return product_model.get_all(active_only=active_only,
                                 include_nonzero_inactive=include_nonzero_inactive)


def get_product_by_barcode(barcode) -> dict | None:
    return product_model.get_by_barcode(barcode)


def get_products_by_barcodes(barcodes) -> list[dict]:
    return product_model.get_by_barcodes(barcodes)


def get_supplier_overrides_for_barcodes(barcodes, supplier_id) -> dict:
    """{barcode: {supplier_sku, pack_qty, pack_unit}} for one supplier — the
    per-supplier SKU/pack size that should be shown on a PO for that
    supplier, rather than the product's default supplier's values."""
    return ps_model.get_map_for_barcodes(barcodes, supplier_id)


def add_product(barcode, description, department_id, supplier_id=None, unit='EA',
                sell_price=0, cost_price=0, tax_rate=0, reorder_point=0,
                reorder_max=0, variable_weight=0, expected=1, brand='',
                plu='', supplier_sku='', base_sku='', pack_qty=1, pack_unit='EA',
                group_id=None) -> None:
    from utils.validators import positive_number, percentage
    if not str(description).strip():
        raise ValueError("Description is required.")
    positive_number(sell_price,   "Sell price")
    positive_number(cost_price,   "Cost price")
    percentage(tax_rate,          "Tax rate")
    positive_number(reorder_point, "Reorder point")
    positive_number(reorder_max,   "Reorder max")
    product_model.create(barcode, description, department_id, supplier_id=supplier_id,
                      unit=unit, sell_price=sell_price, cost_price=cost_price,
                      tax_rate=tax_rate, reorder_point=reorder_point,
                      reorder_max=reorder_max, variable_weight=variable_weight,
                      expected=expected, brand=brand, plu=plu,
                      supplier_sku=supplier_sku, base_sku=base_sku,
                      pack_qty=pack_qty, pack_unit=pack_unit, group_id=group_id)


def search_products(term, active_only=True, limit=None, offset=0) -> list[dict]:
    return product_model.search(term, active_only=active_only, limit=limit, offset=offset)


# ── Stock on hand wrappers ────────────────────────────────────────────────────

def get_soh_by_barcode(barcode) -> dict | None:
    return soh_model.get_by_barcode(barcode)


def get_soh_by_barcodes(barcodes) -> list[dict]:
    return soh_model.get_by_barcodes(barcodes)


def adjust_soh(barcode, quantity, movement_type, reference='', notes='', created_by='') -> None:
    soh_model.adjust(barcode, quantity, movement_type,
                     reference=reference, notes=notes, created_by=created_by)


# ── Barcode alias wrappers ────────────────────────────────────────────────────

def get_aliases(master_barcode) -> list[dict]:
    return alias_model.get_aliases(master_barcode)


def add_alias(alias_barcode, master_barcode, description='') -> None:
    alias_model.add(alias_barcode, master_barcode, description)


def delete_alias(alias_id) -> None:
    alias_model.delete(alias_id)


def get_all_for_pos(limit=200, offset=0) -> list[dict]:
    """Product list with POS-specific fields for cache sync."""
    return product_queries_model.get_all_for_pos(limit, offset)


def get_product_by_plu(plu: int) -> dict | None:
    """
    Look up a product by PLU for POS.
    Tries: plu_barcode_map → products.plu column → product_selling_units.plu column.
    Returns a POS-display dict or None.
    """
    barcode = plu_map_model.find_barcode_by_plu(plu)
    if not barcode:
        barcode = product_plu_model.find_barcode_by_plu(str(plu))
    if not barcode:
        su_barcode = selling_units_model.find_barcode_by_plu(str(plu))
        if su_barcode:
            return get_product_for_pos(su_barcode)
    if not barcode:
        return None
    return product_queries_model.get_with_soh(barcode)


def get_product_for_pos(barcode: str) -> dict | None:
    """
    Get a product with SOH for POS, with selling unit support. Returns dict or None.
    Resolves barcode aliases internally.
    """
    from models.barcode_alias import resolve as _resolve
    resolved = _resolve(barcode)

    row = product_queries_model.get_with_soh(resolved)
    if row:
        return row

    su = selling_units_model.get_for_pos(resolved)
    if su:
        unit_qty = su['unit_qty'] or 0
        soh_in_units = int(su['master_soh'] // unit_qty) if unit_qty > 0 else 0
        return {
            'barcode':        resolved,
            'master_barcode': su['master_barcode'],
            'plu':            su['su_plu'] or su['plu'] or '',
            'description':    su['label'],
            'sell_price':     su['sell_price'],
            'cost_price':     su['cost_price'],
            'tax_rate':       su['tax_rate'],
            'unit':           su['unit'],
            'brand':          su['brand'],
            'dept_name':      su['dept_name'],
            'unit_qty':       su['unit_qty'],
            'soh_qty':        soh_in_units,
        }
    return None
