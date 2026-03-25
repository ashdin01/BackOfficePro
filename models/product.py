from models.barcode_alias import resolve as resolve_barcode
from database.connection import get_connection


def get_all(active_only=True, include_nonzero_inactive=False):
    conn = get_connection()
    if active_only and include_nonzero_inactive:
        # Active products PLUS inactive ones with non-zero stock
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
    rows = conn.execute(query).fetchall()
    conn.close()
    return rows


def get_by_barcode(barcode):
    barcode = resolve_barcode(barcode)
    conn = get_connection()
    row = conn.execute("""
        SELECT p.*, p.plu, d.name as dept_name, s.name as supplier_name,
               g.name as group_name, g.id as group_id_val
        FROM products p
        LEFT JOIN departments d    ON p.department_id = d.id
        LEFT JOIN suppliers s      ON p.supplier_id   = s.id
        LEFT JOIN product_groups g ON p.group_id      = g.id
        WHERE p.barcode = ?
    """, (barcode,)).fetchone()
    conn.close()
    return row


def search(term, active_only=True):
    """
    Multi-word search: splits term into words and requires ALL words
    to appear somewhere in description, barcode, or brand.
    e.g. "oasis dip" finds "OASIS BEETROOT DIP" and "OASIS GARLIC DIP"
    """
    conn = get_connection()
    words = [w.strip() for w in term.strip().split() if w.strip()]
    if not words:
        conn.close()
        return []

    active_clause = "AND p.active = 1" if active_only else ""

    # Build one WHERE clause per word — each word must match at least one column
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

    rows = conn.execute(f"""
        SELECT p.*, p.plu, d.name as dept_name, s.name as supplier_name,
               g.name as group_name, g.id as group_id_val
        FROM products p
        LEFT JOIN departments d    ON p.department_id = d.id
        LEFT JOIN suppliers s      ON p.supplier_id   = s.id
        LEFT JOIN product_groups g ON p.group_id      = g.id
        WHERE {where}
        {active_clause}
        ORDER BY p.active DESC, p.description
    """, params).fetchall()
    conn.close()
    return rows


def add(barcode, description, department_id, supplier_id=None, unit='EA',
        sell_price=0, cost_price=0, tax_rate=0, reorder_point=0,
        reorder_max=0, variable_weight=0, expected=1, brand='',
        plu='', supplier_sku='', pack_qty=1, pack_unit='EA', group_id=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO products
            (barcode, description, brand, plu, supplier_sku, pack_qty, pack_unit,
             group_id, department_id, supplier_id, unit,
             sell_price, cost_price, tax_rate, reorder_point, reorder_max,
             variable_weight, expected)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (barcode, description, brand, plu, supplier_sku, pack_qty, pack_unit,
          group_id, department_id, supplier_id, unit,
          sell_price, cost_price, tax_rate, reorder_point, reorder_max,
          variable_weight, expected))
    conn.commit()
    conn.close()


def update(barcode, description, brand, plu, supplier_sku, pack_qty, pack_unit,
           group_id, department_id, supplier_id, unit,
           sell_price, cost_price, tax_rate, reorder_point, reorder_max=0,
           variable_weight=0, expected=1, active=1):
    conn = get_connection()
    conn.execute("""
        UPDATE products
        SET description=?, brand=?, plu=?, supplier_sku=?, pack_qty=?, pack_unit=?,
            group_id=?, department_id=?, supplier_id=?, unit=?,
            sell_price=?, cost_price=?, tax_rate=?, reorder_point=?,
            reorder_max=?, variable_weight=?, expected=?, active=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE barcode=?
    """, (description, brand, plu, supplier_sku, pack_qty, pack_unit,
          group_id, department_id, supplier_id, unit, sell_price,
          cost_price, tax_rate, reorder_point, reorder_max,
          variable_weight, expected, active, barcode))
    conn.commit()
    conn.close()

def deactivate(barcode):
    conn = get_connection()
    conn.execute("UPDATE products SET active = 0 WHERE barcode = ?", (barcode,))
    conn.commit()
    conn.close()
