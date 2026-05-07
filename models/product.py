from models.barcode_alias import resolve as resolve_barcode
from database.connection import get_connection


def get_all(active_only=True, include_nonzero_inactive=False):
    conn = get_connection()
    try:
        if active_only and include_nonzero_inactive:
            query = """
                SELECT p.*, d.name as dept_name, s.name as supplier_name,
                       g.name as group_name, g.id as group_id_val
                FROM products p
                LEFT JOIN departments d    ON p.department_id = d.id
                LEFT JOIN suppliers s      ON p.supplier_id   = s.id
                LEFT JOIN product_groups g ON p.group_id      = g.id
                LEFT JOIN stock_on_hand soh ON soh.barcode    = p.barcode
                WHERE p.active = 1
                   OR (p.active = 0 AND COALESCE(soh.quantity, 0) != 0)
                ORDER BY p.active DESC, p.description
            """
        elif active_only:
            query = """
                SELECT p.*, d.name as dept_name, s.name as supplier_name,
                       g.name as group_name, g.id as group_id_val
                FROM products p
                LEFT JOIN departments d    ON p.department_id = d.id
                LEFT JOIN suppliers s      ON p.supplier_id   = s.id
                LEFT JOIN product_groups g ON p.group_id      = g.id
                WHERE p.active = 1
                ORDER BY p.description
            """
        else:
            query = """
                SELECT p.*, d.name as dept_name, s.name as supplier_name,
                       g.name as group_name, g.id as group_id_val
                FROM products p
                LEFT JOIN departments d    ON p.department_id = d.id
                LEFT JOIN suppliers s      ON p.supplier_id   = s.id
                LEFT JOIN product_groups g ON p.group_id      = g.id
                ORDER BY p.active DESC, p.description
            """
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def get_by_barcode(barcode):
    barcode = resolve_barcode(barcode)
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT p.*, p.plu, d.name as dept_name, s.name as supplier_name,
                   g.name as group_name, g.id as group_id_val
            FROM products p
            LEFT JOIN departments d    ON p.department_id = d.id
            LEFT JOIN suppliers s      ON p.supplier_id   = s.id
            LEFT JOIN product_groups g ON p.group_id      = g.id
            WHERE p.barcode = ?
        """, (barcode,)).fetchone()
    finally:
        conn.close()


def get_by_barcodes(barcodes):
    """Return {barcode: row} for a list of barcodes in a single query."""
    if not barcodes:
        return {}
    conn = get_connection()
    try:
        placeholders = ','.join('?' * len(barcodes))
        rows = conn.execute(f"""
            SELECT p.*, d.name as dept_name, s.name as supplier_name,
                   g.name as group_name, g.id as group_id_val
            FROM products p
            LEFT JOIN departments d    ON p.department_id = d.id
            LEFT JOIN suppliers s      ON p.supplier_id   = s.id
            LEFT JOIN product_groups g ON p.group_id      = g.id
            WHERE p.barcode IN ({placeholders})
        """, barcodes).fetchall()
        return {r['barcode']: r for r in rows}
    finally:
        conn.close()


def search(term, active_only=True, limit=None, offset=0):
    """
    Multi-word search: splits term into words and requires ALL words
    to appear somewhere in description, barcode, brand, department, supplier, or PLU.
    e.g. "oasis dip" finds "OASIS BEETROOT DIP" and "OASIS GARLIC DIP"

    Optional limit/offset for paginated callers (e.g. the REST API).
    """
    words = [w.strip() for w in term.strip().split() if w.strip()]
    if not words:
        return []

    active_clause = "AND p.active = 1" if active_only else ""

    word_clauses = []
    params = []
    for word in words:
        like = f"%{word}%"
        word_clauses.append(
            "(p.description LIKE ? OR p.barcode LIKE ? OR p.brand LIKE ? OR "
            "d.name LIKE ? OR s.name LIKE ? OR p.plu LIKE ?)"
        )
        params.extend([like, like, like, like, like, like])

    where = " AND ".join(word_clauses)
    limit_clause = "LIMIT ? OFFSET ?" if limit is not None else ""
    if limit is not None:
        params.extend([int(limit), int(offset)])

    conn = get_connection()
    try:
        return conn.execute(f"""
            SELECT p.*, p.plu, d.name as dept_name, s.name as supplier_name,
                   g.name as group_name, g.id as group_id_val
            FROM products p
            LEFT JOIN departments d    ON p.department_id = d.id
            LEFT JOIN suppliers s      ON p.supplier_id   = s.id
            LEFT JOIN product_groups g ON p.group_id      = g.id
            WHERE {where}
            {active_clause}
            ORDER BY p.active DESC, p.description
            {limit_clause}
        """, params).fetchall()
    finally:
        conn.close()


def add(barcode, description, department_id, supplier_id=None, unit='EA',
        sell_price=0, cost_price=0, tax_rate=0, reorder_point=0,
        reorder_max=0, variable_weight=0, expected=1, brand='',
        plu='', supplier_sku='', base_sku='', pack_qty=1, pack_unit='EA', group_id=None):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO products
                (barcode, description, brand, plu, base_sku, supplier_sku, pack_qty, pack_unit,
                 group_id, department_id, supplier_id, unit,
                 sell_price, cost_price, tax_rate, reorder_point, reorder_max,
                 variable_weight, expected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (barcode, description, brand, plu, base_sku, supplier_sku, pack_qty, pack_unit,
              group_id, department_id, supplier_id, unit,
              sell_price, cost_price, tax_rate, reorder_point, reorder_max,
              variable_weight, expected))
        conn.commit()
    finally:
        conn.close()


def update(barcode, description, brand, plu, supplier_sku, pack_qty, pack_unit,
           group_id, department_id, supplier_id, unit,
           sell_price, cost_price, tax_rate, reorder_point, reorder_max=0,
           variable_weight=0, expected=1, active=1, auto_reorder=0):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE products
            SET description=?, brand=?, plu=?, supplier_sku=?, pack_qty=?, pack_unit=?,
                group_id=?, department_id=?, supplier_id=?, unit=?,
                sell_price=?, cost_price=?, tax_rate=?, reorder_point=?,
                reorder_max=?, variable_weight=?, expected=?, active=?, auto_reorder=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE barcode=?
        """, (description, brand, plu, supplier_sku, pack_qty, pack_unit,
              group_id, department_id, supplier_id, unit, sell_price,
              cost_price, tax_rate, reorder_point, reorder_max,
              variable_weight, expected, active, auto_reorder, barcode))
        conn.commit()
    finally:
        conn.close()


def deactivate(barcode):
    conn = get_connection()
    try:
        conn.execute("UPDATE products SET active = 0 WHERE barcode = ?", (barcode,))
        conn.commit()
    finally:
        conn.close()
