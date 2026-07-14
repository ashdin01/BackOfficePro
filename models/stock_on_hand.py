import sqlite3
from datetime import datetime

from config.constants import MOVE_ADJUSTMENT_IN
from database.connection import db_conn


def clamp_negative_soh(conn, barcode, reference='', created_by=''):
    """Reset a negative SOH to zero for products whose department has
    no_negative_soh set (e.g. Fresh — counts drift, so negative SOH is noise).

    Records a compensating ADJUSTMENT_IN movement for the clamped amount so
    movement-based reports still reconcile with the stored SOH.

    Must run inside the caller's transaction, after the SOH write and before
    commit. Returns the clamped quantity (0.0 if nothing was clamped).
    """
    row = conn.execute("""
        SELECT s.quantity
        FROM stock_on_hand s
        JOIN products p    ON p.barcode = s.barcode
        JOIN departments d ON d.id = p.department_id
        WHERE s.barcode = ? AND s.quantity < 0 AND d.no_negative_soh = 1
    """, (barcode,)).fetchone()
    if not row:
        return 0.0

    shortfall = -row['quantity']
    conn.execute(
        "UPDATE stock_on_hand SET quantity = 0, last_updated = CURRENT_TIMESTAMP"
        " WHERE barcode = ?",
        (barcode,)
    )
    from database.audit_context import get_user, get_source
    conn.execute("""
        INSERT INTO stock_movements
            (barcode, movement_type, quantity, reference, notes, created_by, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (barcode, MOVE_ADJUSTMENT_IN, shortfall, reference,
          'Auto-clamp: department does not allow negative SOH',
          created_by or get_user(), get_source()))
    return shortfall


def get_by_barcode(barcode):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM stock_on_hand WHERE barcode = ?", (barcode,)
        ).fetchone()
        return dict(row) if row else None


def get_all_with_product():
    with db_conn() as conn:
        return conn.execute("""
            SELECT s.*, p.description, p.reorder_point, p.reorder_qty, d.name as dept_name
            FROM stock_on_hand s
            JOIN products p     ON s.barcode = p.barcode
            JOIN departments d  ON p.department_id = d.id
            WHERE p.active = 1
            ORDER BY d.name, p.description
        """).fetchall()


def get_below_reorder():
    with db_conn() as conn:
        return conn.execute("""
            SELECT s.barcode, p.description, s.quantity, p.reorder_point, p.reorder_qty,
                   sup.name as supplier_name, d.name as dept_name
            FROM stock_on_hand s
            JOIN products p     ON s.barcode = p.barcode
            JOIN departments d  ON p.department_id = d.id
            LEFT JOIN suppliers sup ON p.supplier_id = sup.id
            WHERE s.quantity < p.reorder_point AND p.active = 1
            ORDER BY p.description
        """).fetchall()


def get_by_barcodes(barcodes):
    """Return a {barcode: quantity} map for a list of barcodes in a single query."""
    if not barcodes:
        return {}
    with db_conn() as conn:
        placeholders = ",".join("?" * len(barcodes))
        rows = conn.execute(
            f"SELECT barcode, quantity FROM stock_on_hand WHERE barcode IN ({placeholders})",
            barcodes
        ).fetchall()
        return {r["barcode"]: r["quantity"] for r in rows}


def adjust(barcode, quantity, movement_type, reference='', notes='', created_by=''):
    from database.audit_context import get_user, get_source
    who = created_by or get_user()
    src = get_source()
    with db_conn() as conn:
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
        clamp_negative_soh(conn, barcode, reference=reference, created_by=who)
        conn.commit()


def record_pos_sale_atomic(reference: str, sale_date: str, operator: str, items: list) -> bool:
    """
    Record a POS sale atomically.

    items: list of {barcode (alias-resolved), qty, line_total, description}

    For each item, resolves selling-unit membership, reduces SOH, writes a
    SALE movement, looks up the PLU, and upserts into sales_daily.
    All writes share one connection and commit together.

    Returns True if the sale was newly recorded, False if this reference was
    already processed (idempotent — caller should respond 200, not 4xx/5xx).

    Raises ValueError if sale_date is not a valid YYYY-MM-DD date.
    """
    try:
        datetime.strptime(sale_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"sale_date must be YYYY-MM-DD, got: {sale_date!r}")

    from database.audit_context import get_source
    src = get_source()
    with db_conn() as conn:
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

            clamp_negative_soh(conn, stock_barcode, reference=reference, created_by=operator)

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
