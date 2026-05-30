import logging
from database.connection import get_connection
from config.constants import PO_STATUS_CANCELLED
from datetime import datetime, timedelta


def _validate_charges(charges: list) -> None:
    """Raise ValueError if any charge dict is malformed.

    Checked before opening a DB connection so callers get a clear error
    rather than a mid-transaction rollback.
    """
    for i, c in enumerate(charges):
        tag = f"charge[{i}]"
        desc = c.get('description', '')
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError(f"{tag}: description must be a non-empty string")
        try:
            tax_rate = float(c['tax_rate'])
        except (TypeError, ValueError, KeyError):
            raise ValueError(f"{tag}: tax_rate must be a number, got {c.get('tax_rate')!r}")
        if not (0.0 <= tax_rate <= 100.0):
            raise ValueError(f"{tag}: tax_rate {tax_rate} is outside 0–100")
        try:
            amount = float(c['amount_inc_tax'])
        except (TypeError, ValueError, KeyError):
            raise ValueError(f"{tag}: amount_inc_tax must be a number, got {c.get('amount_inc_tax')!r}")
        if amount < 0.0:
            raise ValueError(f"{tag}: amount_inc_tax {amount} must be >= 0")


def _next_po_number(conn):
    # Atomic UPDATE+RETURNING increments the counter and returns the old value
    # in one statement — safe when the GUI and Flask API processes run concurrently.
    # The UPDATE and the PO INSERT share the same connection and commit together,
    # so a failed INSERT rolls back the counter increment and no gap occurs.
    prefix = conn.execute("SELECT value FROM settings WHERE key = 'po_prefix'").fetchone()
    row    = conn.execute(
        "UPDATE settings SET value = CAST(value AS INTEGER) + 1"
        " WHERE key = 'po_next_number' RETURNING CAST(value AS INTEGER) - 1",
    ).fetchone()
    number = int(row[0]) if row else 1
    return f"{prefix['value']}-{number:05d}"


def get_all(status=None, archived=False):
    """
    archived=False → active POs (DRAFT, SENT, PARTIAL)
    archived=True  → archived POs (RECEIVED, CANCELLED, REVERSED)
    status=x       → filter by specific status
    """
    conn = get_connection()
    try:
        if status:
            query = """
                SELECT po.*, s.name as supplier_name
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                WHERE po.status = ?
                ORDER BY po.created_at DESC
            """
            return conn.execute(query, (status,)).fetchall()
        elif archived:
            query = """
                SELECT po.*, s.name as supplier_name
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                WHERE po.status IN ('RECEIVED', 'CANCELLED', 'REVERSED', 'CLOSED')
                ORDER BY po.created_at DESC
            """
            return conn.execute(query).fetchall()
        else:
            query = """
                SELECT po.*, s.name as supplier_name
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.id
                WHERE po.status IN ('DRAFT', 'SENT', 'PARTIAL')
                ORDER BY po.created_at DESC
            """
            return conn.execute(query).fetchall()
    finally:
        conn.release()


def get_by_id(po_id):
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.id = ?
        """, (po_id,)).fetchone()
    finally:
        conn.release()


def create(supplier_id, delivery_date=None, notes='', created_by='', po_type='PO'):
    conn = get_connection()
    try:
        po_number = _next_po_number(conn)
        conn.execute("""
            INSERT INTO purchase_orders
                (po_number, supplier_id, delivery_date, notes, created_by, po_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (po_number, supplier_id, delivery_date, notes, created_by, po_type))
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def update_status(po_id, status):
    from models.audit_log import record_changes
    from database.audit_context import get_user
    conn = get_connection()
    try:
        old = conn.execute(
            "SELECT po_number, status FROM purchase_orders WHERE id=?", (po_id,)
        ).fetchone()
        conn.execute(
            "UPDATE purchase_orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, po_id)
        )
        if old:
            record_changes(conn, 'purchase_order', old['po_number'],
                           {'status': old['status']}, {'status': status}, get_user())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def cancel(po_id):
    update_status(po_id, PO_STATUS_CANCELLED)


def reverse(po_id, reversed_by=''):
    """
    Reverse a RECEIVED or PARTIAL PO atomically.
    - Reduces SOH for each received line
    - Records REVERSAL stock movements
    - Sets PO status to REVERSED

    All writes share one connection and commit together.  If any step fails
    the entire reversal rolls back, leaving stock and PO status unchanged.
    """
    from config.constants import MOVE_REVERSAL
    from database.audit_context import get_source, get_user
    from models.audit_log import record_changes

    conn = get_connection()
    try:
        po = conn.execute(
            "SELECT po.*, s.name as supplier_name FROM purchase_orders po "
            "JOIN suppliers s ON po.supplier_id = s.id WHERE po.id = ?",
            (po_id,)
        ).fetchone()
        if not po:
            raise ValueError(f'PO {po_id} not found')
        if po['status'] not in ('RECEIVED', 'PARTIAL'):
            raise ValueError('Only RECEIVED or PARTIAL POs can be reversed')

        lines = conn.execute(
            "SELECT * FROM po_lines WHERE po_id = ?", (po_id,)
        ).fetchall()

        src = get_source()
        for line in lines:
            received = int(line['received_qty'] or 0)
            if received <= 0:
                continue
            pack_qty = int(line['pack_qty']) if line['pack_qty'] else 1
            qty = -(received * pack_qty)
            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (line['barcode'], qty))
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                line['barcode'], MOVE_REVERSAL, qty,
                po['po_number'],
                f"Reversal of {po['po_number']} — {line['description']}",
                reversed_by, src,
            ))

        conn.execute(
            "UPDATE purchase_orders SET status='REVERSED', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (po_id,)
        )
        record_changes(conn, 'purchase_order', po['po_number'],
                       {'status': po['status']}, {'status': 'REVERSED'},
                       reversed_by or get_user())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def get_with_supplier(po_id):
    """Return the PO row joined with supplier name as a dict, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT po.*, s.name AS supplier_name "
            "FROM purchase_orders po "
            "JOIN suppliers s ON s.id = po.supplier_id "
            "WHERE po.id=?",
            (po_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.release()


def close_force(po_id, unreceived_line_ids, reason):
    """Mark listed lines NOT SUPPLIED and set PO status to RECEIVED atomically."""
    conn = get_connection()
    try:
        note = f"NOT SUPPLIED: {reason}"
        for line_id in unreceived_line_ids:
            conn.execute("UPDATE po_lines SET notes=? WHERE id=?", (note, line_id))
        conn.execute(
            "UPDATE purchase_orders SET status='RECEIVED', "
            "received_at=CURRENT_TIMESTAMP WHERE id=?",
            (po_id,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def close_credit_atomic(po_id, po_number, line_receipts):
    """
    Close a Credit/Return PO atomically.
    line_receipts: list of dicts with line_id, barcode, return_cartons, qty_units.
    SOH is reduced by qty_units for each line; movements are RETURN type.
    """
    from database.audit_context import get_user, get_source
    who = get_user()
    src = get_source()
    conn = get_connection()
    try:
        for r in line_receipts:
            conn.execute(
                "UPDATE po_lines SET received_qty=? WHERE id=?",
                (r['return_cartons'], r['line_id'])
            )
            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (r['barcode'], -r['qty_units']))
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source)
                VALUES (?, 'RETURN', ?, ?, '', ?, ?)
            """, (r['barcode'], -r['qty_units'], po_number, who, src))
        conn.execute(
            "UPDATE purchase_orders SET status='CLOSED', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (po_id,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def receive_atomic(po_id, po_number, line_receipts, final_status,
                   supplier_invoice_number='', charges=None):
    """
    Apply a full PO receipt in one atomic transaction.

    line_receipts is a list of dicts:
        line_id, barcode, new_received_qty,
        actual_cost, unit_cost, is_promo,
        qty_units   (number of individual units being received, for SOH)

    charges is an optional list of dicts:
        description (non-empty str), tax_rate (0–100), amount_inc_tax (>= 0)

    Raises ValueError for invalid charge data before any DB writes.
    Raises on any other error; the caller must not catch silently.
    """
    if charges:
        _validate_charges(charges)

    from config.constants import MOVE_RECEIPT
    from database.audit_context import get_user, get_source
    who = get_user()
    src = get_source()
    conn = get_connection()
    try:
        for r in line_receipts:
            fields = ["received_qty=?"]
            params = [r['new_received_qty']]
            if r['actual_cost'] is not None:
                fields.append("actual_cost=?")
                params.append(r['actual_cost'])
            if r['unit_cost'] is not None:
                fields.append("unit_cost=?")
                params.append(r['unit_cost'])
            fields.append("is_promo=?")
            params.append(1 if r['is_promo'] else 0)
            params.append(r['line_id'])
            conn.execute(
                f"UPDATE po_lines SET {', '.join(fields)} WHERE id=?", params
            )

            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (r['barcode'], r['qty_units']))
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source)
                VALUES (?, ?, ?, ?, '', ?, ?)
            """, (r['barcode'], MOVE_RECEIPT, r['qty_units'], po_number, who, src))

            if r['unit_cost'] and r['unit_cost'] > 0 and not r['is_promo']:
                conn.execute(
                    "UPDATE products SET cost_price=?, updated_at=CURRENT_TIMESTAMP"
                    " WHERE barcode=?",
                    (r['unit_cost'], r['barcode'])
                )

        conn.execute(
            "UPDATE purchase_orders SET status=?, supplier_invoice_number=?,"
            " updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (final_status, supplier_invoice_number, po_id)
        )
        if charges:
            conn.execute("DELETE FROM po_charges WHERE po_id=?", (po_id,))
            for c in charges:
                conn.execute(
                    "INSERT INTO po_charges (po_id, description, tax_rate, amount_inc_tax)"
                    " VALUES (?,?,?,?)",
                    (po_id, c['description'].strip(),
                     float(c['tax_rate']),
                     float(c['amount_inc_tax']))
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def cleanup_old_pos():
    """
    Delete CANCELLED POs older than 24 hours (and their lines).
    Returns count of deleted POs.
    """
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute("""
            DELETE FROM po_lines
            WHERE po_id IN (
                SELECT id FROM purchase_orders
                WHERE status = 'CANCELLED'
                AND COALESCE(updated_at, created_at) < ?
            )
        """, (cutoff,))
        cursor = conn.execute("""
            DELETE FROM purchase_orders
            WHERE status = 'CANCELLED'
            AND COALESCE(updated_at, created_at) < ?
        """, (cutoff,))
        count = cursor.rowcount
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        logging.error("PO cleanup failed", exc_info=True)
        raise
    finally:
        conn.release()
