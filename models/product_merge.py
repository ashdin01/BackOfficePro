"""Merge a duplicate product into another ("keeper") product.

The keeper's price, description, department, supplier etc. are left untouched.
Everything that references the duplicate's barcode is re-pointed to the keeper,
the duplicate's stock on hand is added to the keeper's, and the duplicate's own
barcode becomes an alternate barcode (alias) of the keeper. The duplicate
product row is then deleted. All of it happens in one transaction.

Every table with a barcode column must be handled here or refused up front;
tests/test_models_product_merge.py fails if a new such table appears.
"""
from database.connection import db_conn
from database import audit_context
from models import audit_log

# Tables whose `barcode` column is simply re-pointed.
_REPOINT = (
    "stock_movements", "po_lines", "product_batches", "ar_invoice_lines",
    "pos_refund_lines", "held_sale_lines", "plu_barcode_map",
)
# Handled with custom logic below.
_CUSTOM = (
    "products", "stock_on_hand", "barcode_aliases", "product_suppliers",
    "stocktake_counts", "bundle_eligible",
)
# Merge is refused when the duplicate/keeper appears in these.
_REFUSED = ("product_selling_units", "kit_components", "kit_builds")
HANDLED_TABLES = frozenset(_REPOINT + _CUSTOM + _REFUSED)


def resolve_target(text):
    """Find a product from a barcode, alias barcode or PLU. Returns row or None."""
    text = (text or "").strip()
    if not text:
        return None
    with db_conn() as conn:
        row = conn.execute("""
            SELECT * FROM products WHERE barcode = COALESCE(
                (SELECT master_barcode FROM barcode_aliases WHERE alias_barcode = ?), ?)
        """, (text, text)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM products WHERE plu IN (?, ?) ORDER BY active DESC LIMIT 1",
                (text, text.lstrip("0") or text)).fetchone()
        return row


def _blockers(conn, dup, keeper):
    if dup == keeper:
        return ["A product cannot be merged into itself."]
    out = []
    for bc, name in ((dup, "the duplicate"), (keeper, "the target")):
        if not conn.execute("SELECT 1 FROM products WHERE barcode=?", (bc,)).fetchone():
            out.append(f"Product {bc} was not found.")
    if out:
        return out
    for bc, name in ((dup, "duplicate"), (keeper, "target")):
        if conn.execute("SELECT 1 FROM kit_components WHERE parent_barcode=? OR component_barcode=?",
                        (bc, bc)).fetchone() or \
           conn.execute("SELECT 1 FROM kit_builds WHERE parent_barcode=?", (bc,)).fetchone():
            out.append(f"The {name} product is part of a kit. Remove it from the kit first.")
    if conn.execute("SELECT 1 FROM product_selling_units WHERE master_barcode=?", (dup,)).fetchone():
        out.append("The duplicate has selling units (case/pack). Remove or move them first.")
    if conn.execute("SELECT 1 FROM product_selling_units WHERE barcode IN (?,?)", (dup, keeper)).fetchone():
        out.append("One of the products is a selling unit of another product.")
    return out


def preview(dup, keeper):
    """Describe what a merge would do. Raises ValueError listing any blockers."""
    with db_conn() as conn:
        blockers = _blockers(conn, dup, keeper)
        if blockers:
            raise ValueError("\n".join(blockers))
        n = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
        d = conn.execute("SELECT barcode, description, plu FROM products WHERE barcode=?", (dup,)).fetchone()
        k = conn.execute("SELECT barcode, description, plu FROM products WHERE barcode=?", (keeper,)).fetchone()
        soh = lambda bc: n("SELECT COALESCE((SELECT quantity FROM stock_on_hand WHERE barcode=?),0)", bc)
        return {
            "dup": dict(d), "keeper": dict(k),
            "dup_soh": soh(dup), "keeper_soh": soh(keeper),
            "movements": n("SELECT COUNT(*) FROM stock_movements WHERE barcode=?", dup),
            "po_lines": n("SELECT COUNT(*) FROM po_lines WHERE barcode=?", dup),
            "open_po_lines": n("""SELECT COUNT(*) FROM po_lines l JOIN purchase_orders p ON p.id=l.po_id
                                  WHERE l.barcode=? AND p.status IN ('DRAFT','SENT','PARTIAL')""", dup),
            "stocktake_counts": n("SELECT COUNT(*) FROM stocktake_counts WHERE barcode=?", dup),
            "aliases": n("SELECT COUNT(*) FROM barcode_aliases WHERE master_barcode=? AND alias_barcode!=?", dup, dup),
        }


def merge(dup, keeper, user=None):
    """Merge `dup` into `keeper` atomically. Raises ValueError if refused."""
    user = user if user is not None else audit_context.get_user()
    with db_conn() as conn:
        blockers = _blockers(conn, dup, keeper)
        if blockers:
            raise ValueError("\n".join(blockers))
        dup_desc = conn.execute("SELECT description FROM products WHERE barcode=?", (dup,)).fetchone()[0]
        dup_soh = conn.execute("SELECT COALESCE((SELECT quantity FROM stock_on_hand WHERE barcode=?),0)",
                               (dup,)).fetchone()[0]

        # Plain re-points
        for t in _REPOINT:
            conn.execute(f"UPDATE {t} SET barcode=? WHERE barcode=?", (keeper, dup))

        # Stock on hand: add to the keeper's row (create it if missing)
        conn.execute("INSERT OR IGNORE INTO stock_on_hand (barcode, quantity) VALUES (?, 0)", (keeper,))
        conn.execute("""UPDATE stock_on_hand SET quantity = quantity + ?, last_updated = CURRENT_TIMESTAMP
                        WHERE barcode=?""", (dup_soh, keeper))
        conn.execute("DELETE FROM stock_on_hand WHERE barcode=?", (dup,))

        # Stocktake counts: UNIQUE(session, barcode) -> sum where both were counted
        conn.execute("""
            UPDATE stocktake_counts SET counted_qty = counted_qty + (
                SELECT d.counted_qty FROM stocktake_counts d
                WHERE d.session_id = stocktake_counts.session_id AND d.barcode = ?)
            WHERE barcode = ? AND session_id IN (SELECT session_id FROM stocktake_counts WHERE barcode = ?)
        """, (dup, keeper, dup))
        conn.execute("""DELETE FROM stocktake_counts WHERE barcode=? AND session_id IN
                        (SELECT session_id FROM stocktake_counts WHERE barcode=?)""", (dup, keeper))
        conn.execute("UPDATE stocktake_counts SET barcode=? WHERE barcode=?", (keeper, dup))

        # Bundles: UNIQUE(bundle, barcode)
        conn.execute("""DELETE FROM bundle_eligible WHERE barcode=? AND bundle_id IN
                        (SELECT bundle_id FROM bundle_eligible WHERE barcode=?)""", (dup, keeper))
        conn.execute("UPDATE bundle_eligible SET barcode=? WHERE barcode=?", (keeper, dup))

        # Supplier links: UNIQUE(barcode, supplier); keeper's links/default win
        conn.execute("""DELETE FROM product_suppliers WHERE barcode=? AND supplier_id IN
                        (SELECT supplier_id FROM product_suppliers WHERE barcode=?)""", (dup, keeper))
        if conn.execute("SELECT 1 FROM product_suppliers WHERE barcode=?", (keeper,)).fetchone():
            conn.execute("UPDATE product_suppliers SET is_default=0 WHERE barcode=?", (dup,))
        conn.execute("UPDATE product_suppliers SET barcode=? WHERE barcode=?", (keeper, dup))

        # Aliases: move the duplicate's aliases, drop any row for the dup barcode
        # itself (including a self-alias), then make the dup barcode an alias.
        conn.execute("DELETE FROM barcode_aliases WHERE alias_barcode=?", (dup,))
        conn.execute("UPDATE barcode_aliases SET master_barcode=? WHERE master_barcode=?", (keeper, dup))
        conn.execute("""INSERT INTO barcode_aliases (alias_barcode, master_barcode, description)
                        VALUES (?,?,?)""", (dup, keeper, f"Merged from {dup_desc}"[:200]))

        conn.execute("DELETE FROM products WHERE barcode=?", (dup,))
        audit_log._write(conn, "product", keeper, "merged_from", "", f"{dup} ({dup_desc}), SOH {dup_soh:g}", user)
        audit_log._write(conn, "product", dup, "merged_into", "", keeper, user)
        conn.commit()
