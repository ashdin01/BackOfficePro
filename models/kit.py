"""Model for kits (pre-assembled products such as Xmas hampers).

A kit is an ordinary product with its own barcode/PLU and stock_on_hand. Its
recipe (kit_components) lists the component products and how many go into one
kit. build() consumes components and produces kits in one transaction; sales
of the kit then only ever reduce the kit's own stock.
"""
import math

from config.constants import MOVE_ASSEMBLY_IN, MOVE_ASSEMBLY_OUT, MOVE_REVALUE
from database.connection import db_conn
from models.stock_on_hand import clamp_negative_soh


# ── Recipe ────────────────────────────────────────────────────────────────────

def get_kits():
    """Return every product that has a recipe, with its stock and recipe size."""
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT p.barcode, p.plu, p.description, p.cost_price,
                   COALESCE(s.quantity, 0) AS soh,
                   COUNT(k.id)             AS component_count
            FROM kit_components k
            JOIN products p            ON p.barcode = k.parent_barcode
            LEFT JOIN stock_on_hand s  ON s.barcode = p.barcode
            GROUP BY p.barcode
            ORDER BY p.description
        """).fetchall()
        return [dict(r) for r in rows]


def get_components(parent_barcode):
    """Return the recipe lines for a kit with component cost and current stock."""
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT k.id, k.component_barcode AS barcode, k.qty,
                   p.plu, p.description, p.cost_price,
                   COALESCE(s.quantity, 0) AS soh
            FROM kit_components k
            JOIN products p           ON p.barcode = k.component_barcode
            LEFT JOIN stock_on_hand s ON s.barcode = k.component_barcode
            WHERE k.parent_barcode = ?
            ORDER BY p.description
        """, (parent_barcode,)).fetchall()
        return [dict(r) for r in rows]


def add_component(parent_barcode, component_barcode, qty=1):
    """Add a component to a kit's recipe and return the new row id.

    Raises ValueError for a self-reference, a duplicate, an unknown product,
    or an attempt to nest kits (a kit inside a kit, in either direction) —
    builds consume components directly, so nesting would silently leave the
    inner kit's own components untouched.
    """
    if parent_barcode == component_barcode:
        raise ValueError("A kit cannot contain itself.")
    if not qty or float(qty) <= 0:
        raise ValueError("Component quantity must be greater than zero.")
    with db_conn() as conn:
        for bc in (parent_barcode, component_barcode):
            if not conn.execute("SELECT 1 FROM products WHERE barcode=?", (bc,)).fetchone():
                raise ValueError(f"Product {bc} not found.")
        if conn.execute(
            "SELECT 1 FROM kit_components WHERE parent_barcode=?", (component_barcode,)
        ).fetchone():
            raise ValueError("That product is itself a kit — kits cannot be nested.")
        if conn.execute(
            "SELECT 1 FROM kit_components WHERE component_barcode=?", (parent_barcode,)
        ).fetchone():
            raise ValueError("This product is a component of another kit — kits cannot be nested.")
        if conn.execute(
            "SELECT 1 FROM kit_components WHERE parent_barcode=? AND component_barcode=?",
            (parent_barcode, component_barcode)
        ).fetchone():
            raise ValueError("That product is already in this kit.")
        cur = conn.execute(
            "INSERT INTO kit_components (parent_barcode, component_barcode, qty) VALUES (?,?,?)",
            (parent_barcode, component_barcode, float(qty))
        )
        conn.commit()
        return cur.lastrowid


def update_component_qty(component_id, qty):
    if not qty or float(qty) <= 0:
        raise ValueError("Component quantity must be greater than zero.")
    with db_conn() as conn:
        conn.execute("UPDATE kit_components SET qty=? WHERE id=?", (float(qty), component_id))
        conn.commit()


def delete_component(component_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM kit_components WHERE id=?", (component_id,))
        conn.commit()


def get_recipe_cost(parent_barcode):
    """Sum of component cost_price × qty for one kit (ex GST, as stored)."""
    return round(sum(
        (c['cost_price'] or 0) * c['qty'] for c in get_components(parent_barcode)
    ), 4)


def get_shortages(parent_barcode, qty):
    """Components whose on-hand stock won't cover building qty kits.

    Returns [{'description', 'need', 'have'}]; informational only — build()
    does not block on it.
    """
    if qty <= 0:
        return []
    return [
        {'description': c['description'], 'need': c['qty'] * qty, 'have': c['soh']}
        for c in get_components(parent_barcode)
        if c['soh'] + 1e-9 < c['qty'] * qty
    ]


def get_max_buildable(parent_barcode):
    """How many whole kits current component stock allows (0 if no recipe)."""
    comps = get_components(parent_barcode)
    if not comps:
        return 0
    return max(0, min(math.floor((c['soh'] + 1e-9) / c['qty']) for c in comps))


# ── Build / break down ────────────────────────────────────────────────────────

def _move(conn, barcode, qty, movement_type, reference, notes, who, src):
    conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity)
        VALUES (?, ?)
        ON CONFLICT(barcode) DO UPDATE SET
            quantity = quantity + excluded.quantity,
            last_updated = CURRENT_TIMESTAMP
    """, (barcode, qty))
    conn.execute("""
        INSERT INTO stock_movements
            (barcode, movement_type, quantity, reference, notes, created_by, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (barcode, movement_type, qty, reference, notes, who, src))


def build(parent_barcode, qty, notes='', created_by=''):
    """Assemble (qty > 0) or break down (qty < 0) kits atomically; return build id.

    Assemble: components −(recipe qty × n), kit +n, kit cost_price reset to the
    current recipe cost (a REVALUE row prices any kits already on the shelf, as
    a PO receipt does). Break down: the reverse, with no cost change.

    A build is never blocked by component stock: counts drift, so a component
    may legitimately sit at or below zero on the system while the units are on
    the bench (departments with no_negative_soh are clamped back to 0 as with
    any other stock write; get_shortages() lets a caller warn first). Raises
    ValueError, writing nothing, if the kit has no recipe or a break-down
    exceeds the kits on hand.
    """
    from database.audit_context import get_user, get_source
    who = created_by or get_user()
    src = get_source()
    n = abs(float(qty))
    if not n:
        raise ValueError("Quantity must not be zero.")
    assembling = float(qty) > 0

    with db_conn() as conn:
        parent = conn.execute(
            "SELECT barcode, description, cost_price FROM products WHERE barcode=?",
            (parent_barcode,)
        ).fetchone()
        if not parent:
            raise ValueError(f"Product {parent_barcode} not found.")
        comps = conn.execute("""
            SELECT k.component_barcode AS barcode, k.qty, p.description, p.cost_price,
                   COALESCE(s.quantity, 0) AS soh
            FROM kit_components k
            JOIN products p           ON p.barcode = k.component_barcode
            LEFT JOIN stock_on_hand s ON s.barcode = k.component_barcode
            WHERE k.parent_barcode = ?
        """, (parent_barcode,)).fetchall()
        if not comps:
            raise ValueError(f"{parent['description']} has no components defined.")
        parent_soh = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM stock_on_hand WHERE barcode=?",
            (parent_barcode,)
        ).fetchone()[0]

        if not assembling and parent_soh + 1e-9 < n:
            raise ValueError(f"Only {parent_soh:g} × {parent['description']} on hand; "
                             f"cannot break down {n:g}.")

        unit_cost = round(sum((c['cost_price'] or 0) * c['qty'] for c in comps), 4)
        build_id = conn.execute(
            "INSERT INTO kit_builds (parent_barcode, qty, unit_cost, notes, created_by)"
            " VALUES (?,?,?,?,?)",
            (parent_barcode, float(qty), unit_cost, notes or '', who)
        ).lastrowid
        ref = f"ASM-{build_id}"

        if assembling:
            for c in comps:
                _move(conn, c['barcode'], -c['qty'] * n, MOVE_ASSEMBLY_OUT, ref,
                      f"Built {n:g} × {parent['description']}", who, src)
                clamp_negative_soh(conn, c['barcode'], reference=ref, created_by=who)

            old_cost = parent['cost_price']
            if unit_cost > 0 and old_cost is not None and float(old_cost) != unit_cost:
                if parent_soh > 0:
                    value_delta = (unit_cost - float(old_cost)) * float(parent_soh)
                    conn.execute("""
                        INSERT INTO stock_movements
                            (barcode, movement_type, quantity, reference, notes,
                             created_by, source, old_cost, new_cost, value_delta)
                        VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                    """, (parent_barcode, MOVE_REVALUE, ref,
                          f"Cost changed ${float(old_cost):.2f} → ${unit_cost:.2f}"
                          f"  |  {parent_soh:.0f} units on hand revalued"
                          f"  |  value {'+' if value_delta >= 0 else ''}{value_delta:.2f}",
                          who, src, old_cost, unit_cost, value_delta))
                conn.execute(
                    "UPDATE products SET cost_price=?, updated_at=CURRENT_TIMESTAMP WHERE barcode=?",
                    (unit_cost, parent_barcode)
                )
            _move(conn, parent_barcode, n, MOVE_ASSEMBLY_IN, ref,
                  f"Built from components (${unit_cost:.2f} each)", who, src)
        else:
            _move(conn, parent_barcode, -n, MOVE_ASSEMBLY_OUT, ref,
                  "Broken down into components", who, src)
            clamp_negative_soh(conn, parent_barcode, reference=ref, created_by=who)
            for c in comps:
                _move(conn, c['barcode'], c['qty'] * n, MOVE_ASSEMBLY_IN, ref,
                      f"Returned from {n:g} × {parent['description']}", who, src)

        conn.commit()
        return build_id


def get_builds(parent_barcode=None, limit=100):
    """Recent assembly / break-down runs, newest first."""
    with db_conn() as conn:
        sql = """
            SELECT b.id, b.parent_barcode, p.description, b.qty, b.unit_cost,
                   b.notes, b.created_by, b.created_at
            FROM kit_builds b
            JOIN products p ON p.barcode = b.parent_barcode
        """
        params = []
        if parent_barcode:
            sql += " WHERE b.parent_barcode = ?"
            params.append(parent_barcode)
        sql += " ORDER BY b.id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
