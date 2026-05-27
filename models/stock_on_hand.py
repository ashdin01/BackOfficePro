import sqlite3

from database.connection import get_connection


def get_by_barcode(barcode):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM stock_on_hand WHERE barcode = ?", (barcode,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


def get_all_with_product():
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT s.*, p.description, p.reorder_point, p.reorder_qty, d.name as dept_name
            FROM stock_on_hand s
            JOIN products p     ON s.barcode = p.barcode
            JOIN departments d  ON p.department_id = d.id
            WHERE p.active = 1
            ORDER BY d.name, p.description
        """).fetchall()
    finally:
        conn.release()


def get_below_reorder():
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT s.barcode, p.description, s.quantity, p.reorder_point, p.reorder_qty,
                   sup.name as supplier_name, d.name as dept_name
            FROM stock_on_hand s
            JOIN products p     ON s.barcode = p.barcode
            JOIN departments d  ON p.department_id = d.id
            LEFT JOIN suppliers sup ON p.supplier_id = sup.id
            WHERE s.quantity <= p.reorder_point AND p.active = 1
            ORDER BY p.description
        """).fetchall()
    finally:
        conn.release()


def get_by_barcodes(barcodes):
    """Return a {barcode: quantity} map for a list of barcodes in a single query."""
    if not barcodes:
        return {}
    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(barcodes))
        rows = conn.execute(
            f"SELECT barcode, quantity FROM stock_on_hand WHERE barcode IN ({placeholders})",
            barcodes
        ).fetchall()
        return {r["barcode"]: r["quantity"] for r in rows}
    finally:
        conn.release()


def adjust(barcode, quantity, movement_type, reference='', notes='', created_by=''):
    from database.audit_context import get_user, get_source
    who = created_by or get_user()
    src = get_source()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO stock_on_hand (barcode, quantity)
            VALUES (?, ?)
            ON CONFLICT(barcode) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                last_updated = CURRENT_TIMESTAMP
        """, (barcode, quantity))
        conn.execute("""
            INSERT INTO stock_movements
                (barcode, movement_type, quantity, reference, notes, created_by, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (barcode, movement_type, quantity, reference, notes, who, src))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def record_pos_sale_atomic(reference: str, sale_date: str, operator: str, items: list) -> bool:
    """
    Record a POS sale atomically.

    items: list of {barcode (alias-resolved), qty, line_total, description}

    For each item, resolves selling-unit membership, reduces SOH, writes a
    SALE movement, looks up the PLU, and upserts into sales_daily.
    All writes share one connection and commit together.

    Returns True if the sale was newly recorded, False if this reference was
    already processed (idempotent — caller should respond 200, not 4xx/5xx).
    """
    from database.audit_context import get_source
    src = get_source()
    conn = get_connection()
    try:
        # Idempotency gate: claim the reference before touching stock.
        # If the POS retries after a network timeout, this INSERT fails and
        # we return False without touching SOH or movements a second time.
        try:
            conn.execute(
                "INSERT INTO pos_sales (reference, sale_date, operator) VALUES (?, ?, ?)",
                (reference, sale_date, operator),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            return False

        for item in items:
            barcode     = item['barcode']
            qty         = float(item['qty'])
            line_total  = float(item['line_total'])
            description = item.get('description', '')

            if not barcode or qty <= 0:
                continue

            su = conn.execute(
                "SELECT master_barcode, unit_qty FROM product_selling_units "
                "WHERE barcode = ? AND active = 1",
                (barcode,)
            ).fetchone()
            if su:
                stock_barcode = su['master_barcode']
                stock_qty     = qty * (su['unit_qty'] or 1)
            else:
                stock_barcode = barcode
                stock_qty     = qty

            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (stock_barcode, -stock_qty))

            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source)
                VALUES (?, 'SALE', ?, ?, ?, ?, ?)
            """, (stock_barcode, -stock_qty, reference, description, operator, src))

            plu_row = conn.execute(
                "SELECT plu FROM products WHERE barcode = ?", (stock_barcode,)
            ).fetchone()
            plu = (plu_row['plu'] or stock_barcode) if plu_row and plu_row['plu'] else stock_barcode

            conn.execute("""
                INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sale_date, plu) DO UPDATE SET
                    quantity      = quantity      + excluded.quantity,
                    sales_dollars = sales_dollars + excluded.sales_dollars
            """, (sale_date, plu, description, qty, line_total))

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()
