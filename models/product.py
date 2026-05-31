from database.connection import db_conn


def get_all(active_only=True, include_nonzero_inactive=False):
    with db_conn() as conn:
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


def get_by_barcode(barcode):
    with db_conn() as conn:
        return conn.execute("""
            SELECT p.*, p.plu, d.name as dept_name, s.name as supplier_name,
                   g.name as group_name, g.id as group_id_val
            FROM products p
            LEFT JOIN departments d    ON p.department_id = d.id
            LEFT JOIN suppliers s      ON p.supplier_id   = s.id
            LEFT JOIN product_groups g ON p.group_id      = g.id
            WHERE p.barcode = COALESCE(
                (SELECT master_barcode FROM barcode_aliases WHERE alias_barcode = ?),
                ?
            )
        """, (barcode, barcode)).fetchone()


def get_by_barcodes(barcodes):
    """Return {barcode: row} for a list of barcodes in a single query."""
    if not barcodes:
        return {}
    with db_conn() as conn:
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

    with db_conn() as conn:
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


def create(barcode, description, department_id, supplier_id=None, unit='EA',
        sell_price=0, cost_price=0, tax_rate=0, reorder_point=0,
        reorder_max=0, variable_weight=0, expected=1, brand='',
        plu='', supplier_sku='', base_sku='', pack_qty=1, pack_unit='EA', group_id=None):
    with db_conn() as conn:
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


def update(barcode, description, brand, plu, supplier_sku, pack_qty, pack_unit,
           group_id, department_id, supplier_id, unit,
           sell_price, cost_price, tax_rate, reorder_point, reorder_max=0,
           variable_weight=0, expected=1, active=1, auto_reorder=0):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute("SELECT * FROM products WHERE barcode=?", (barcode,)).fetchone()
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
        new = dict(description=description, brand=brand, plu=plu, supplier_sku=supplier_sku,
                   pack_qty=pack_qty, pack_unit=pack_unit, group_id=group_id,
                   department_id=department_id, supplier_id=supplier_id, unit=unit,
                   sell_price=sell_price, cost_price=cost_price, tax_rate=tax_rate,
                   reorder_point=reorder_point, reorder_max=reorder_max,
                   variable_weight=variable_weight, expected=expected,
                   active=active, auto_reorder=auto_reorder)
        record_changes(conn, 'product', barcode, dict(old) if old else {}, new, get_user())
        conn.commit()


def deactivate(barcode):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute("SELECT active FROM products WHERE barcode=?", (barcode,)).fetchone()
        conn.execute("UPDATE products SET active = 0 WHERE barcode = ?", (barcode,))
        record_changes(conn, 'product', barcode,
                       {'active': old['active']} if old else {},
                       {'active': 0}, get_user())
        conn.commit()


def update_cost_price(barcode, cost):
    """Update the cost_price on the product master record."""
    from models.audit_log import record_changes
    from database.audit_context import get_user
    with db_conn() as conn:
        old = conn.execute("SELECT cost_price FROM products WHERE barcode=?", (barcode,)).fetchone()
        conn.execute(
            "UPDATE products SET cost_price=?, updated_at=CURRENT_TIMESTAMP WHERE barcode=?",
            (cost, barcode)
        )
        record_changes(conn, 'product', barcode,
                       {'cost_price': old['cost_price'] if old else None},
                       {'cost_price': cost}, get_user())
        conn.commit()


def check_barcode_available(barcode):
    """Returns the description of the product using this barcode, or None if free."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT description FROM products WHERE barcode=?", (barcode,)
        ).fetchone()
        return row['description'] if row else None


def rename_barcode(old_bc, new_bc):
    """
    Rename a barcode across all referencing tables atomically.
    Raises ValueError if new_bc is already in use.
    Raises on DB error after rolling back.
    """
    import logging
    owner = check_barcode_available(new_bc)
    if owner is not None:
        raise ValueError(f"Barcode {new_bc!r} already belongs to: {owner}")

    with db_conn() as conn:
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


def barcode_exists(barcode: str) -> bool:
    """Return True if the barcode exists in the products table."""
    with db_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM products WHERE barcode=?", (barcode,)
        ).fetchone() is not None


def get_all_with_stock() -> list:
    """All active products joined with dept, supplier, and stock on hand."""
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT p.barcode, p.plu, p.description, p.brand,
                   d.name  AS dept_name,
                   s.name  AS supplier_name,
                   p.unit, p.sell_price, p.cost_price,
                   COALESCE(soh.quantity, 0) AS on_hand
            FROM products p
            LEFT JOIN departments   d   ON p.department_id = d.id
            LEFT JOIN suppliers     s   ON p.supplier_id   = s.id
            LEFT JOIN stock_on_hand soh ON soh.barcode     = p.barcode
            WHERE p.active = 1
        """).fetchall()
        return [dict(r) for r in rows]
