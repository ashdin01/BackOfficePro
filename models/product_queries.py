"""Specialised read queries for products — supplier ordering, POS display, and SOH joins."""
from database.connection import get_connection


def get_reorder_candidates(supplier_id) -> list:
    """
    Products linked to supplier_id whose SOH is at or below their reorder point.
    Returns list of dicts with barcode, description, reorder_point, reorder_max,
    cost_price, on_hand, pack_qty, pack_unit, supplier_sku.
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.barcode, p.description, p.reorder_point,
                   COALESCE(p.reorder_max, 0) AS reorder_max,
                   p.cost_price, COALESCE(s.quantity, 0) AS on_hand,
                   COALESCE(p.pack_qty, 1) AS pack_qty,
                   COALESCE(p.pack_unit, 'EA') AS pack_unit,
                   p.supplier_sku
            FROM products p
            LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
            WHERE p.supplier_id = ?
              AND p.active = 1
              AND COALESCE(s.quantity, 0) <= p.reorder_point
              AND p.reorder_point > 0
            ORDER BY p.description
        """, (supplier_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()


def get_auto_reorder_items(supplier_id) -> list:
    """Products flagged auto_reorder = 1 for this supplier."""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT p.barcode, p.description, p.reorder_point,
                   COALESCE(p.reorder_max, 0) AS reorder_max,
                   p.cost_price, COALESCE(s.quantity, 0) AS on_hand,
                   COALESCE(p.pack_qty, 1) AS pack_qty,
                   COALESCE(p.pack_unit, 'EA') AS pack_unit,
                   p.supplier_sku
            FROM products p
            LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
            WHERE p.supplier_id = ? AND p.auto_reorder = 1 AND p.active = 1
            ORDER BY p.description
        """, (supplier_id,)).fetchall()]
    finally:
        conn.release()


def get_items_for_supplier(supplier_id=None) -> list:
    """
    Return active products for the item lookup dialog.
    If supplier_id is given, return all products linked to that supplier via
    product_suppliers (not just those whose default supplier matches).
    Rows include: supplier_name, barcode, description, pack_qty, pack_unit, cost_price.
    """
    conn = get_connection()
    try:
        if supplier_id:
            return conn.execute("""
                SELECT COALESCE(s.name, '') AS supplier_name,
                       p.barcode, p.description,
                       COALESCE(ps.pack_qty, p.pack_qty, 1) AS pack_qty,
                       COALESCE(ps.pack_unit, p.pack_unit, 'EA') AS pack_unit,
                       COALESCE(p.cost_price, 0.0) AS cost_price
                FROM products p
                JOIN product_suppliers ps ON p.barcode = ps.barcode AND ps.supplier_id = ?
                JOIN suppliers s ON s.id = ?
                WHERE p.active = 1
                ORDER BY p.description ASC
            """, (supplier_id, supplier_id)).fetchall()
        else:
            return conn.execute("""
                SELECT COALESCE(s.name, '') AS supplier_name,
                       p.barcode, p.description,
                       COALESCE(p.pack_qty, 1) AS pack_qty,
                       COALESCE(p.pack_unit, 'EA') AS pack_unit,
                       COALESCE(p.cost_price, 0.0) AS cost_price
                FROM products p
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                WHERE p.active = 1
                ORDER BY supplier_name ASC, p.description ASC
            """).fetchall()
    finally:
        conn.release()


def get_milk_products(supplier_id) -> list:
    """
    Products in the DAIRY department / MILK group for a given supplier.
    Returns list of dicts with barcode, description, cost_price, pack_qty,
    pack_unit, on_hand, supplier_sku.
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.barcode, p.description,
                   COALESCE(p.cost_price, 0)   AS cost_price,
                   COALESCE(p.pack_qty, 1)     AS pack_qty,
                   COALESCE(p.pack_unit, 'EA') AS pack_unit,
                   COALESCE(soh.quantity, 0)   AS on_hand,
                   p.supplier_sku
            FROM products p
            JOIN product_groups  pg  ON p.group_id       = pg.id
            JOIN departments     d   ON pg.department_id = d.id
            LEFT JOIN stock_on_hand soh ON p.barcode     = soh.barcode
            WHERE p.supplier_id = ?
              AND p.active = 1
              AND UPPER(d.name)  = 'DAIRY'
              AND UPPER(pg.name) = 'MILK'
            ORDER BY p.description
        """, (supplier_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()


def get_sku(barcode) -> str | None:
    """Return the sku field for a product, or None if not found."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT sku FROM products WHERE barcode=?", (barcode,)
        ).fetchone()
        return row['sku'] if row and row['sku'] else None
    finally:
        conn.release()


def get_with_soh(barcode) -> dict | None:
    """Product with SOH quantity for POS. Returns dict or None. Product must be active."""
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT p.barcode, p.plu, p.description, p.sell_price, p.cost_price,
                   p.tax_rate, p.unit, p.brand, d.name AS dept_name,
                   COALESCE(soh.quantity, 0) AS soh_qty
            FROM products p
            LEFT JOIN departments d     ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh ON soh.barcode = p.barcode
            WHERE p.barcode = ? AND p.active = 1
        """, (barcode,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


def get_all_for_pos(limit=200, offset=0) -> list:
    """Minimal product fields for POS cache sync (barcode, plu, description, price, etc.)."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.barcode, p.plu, p.description, p.brand, p.unit,
                   p.sell_price, p.tax_rate, d.name AS dept_name,
                   g.name AS group_name
            FROM products p
            LEFT JOIN departments d    ON p.department_id = d.id
            LEFT JOIN product_groups g ON p.group_id = g.id
            WHERE p.active = 1
            ORDER BY p.description
            LIMIT ? OFFSET ?
        """, (int(limit), int(offset))).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.release()
