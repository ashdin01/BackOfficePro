from database.connection import get_connection


def get_all(active_only=False):
    conn = get_connection()
    try:
        q = "SELECT * FROM bundles"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY name"
        return conn.execute(q).fetchall()
    finally:
        conn.close()


def get_by_id(bundle_id):
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM bundles WHERE id=?", (bundle_id,)).fetchone()
    finally:
        conn.close()


def add(name, description, required_qty, price):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO bundles (name, description, required_qty, price) VALUES (?,?,?,?)",
            (name, description or '', required_qty, price)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update(bundle_id, name, description, required_qty, price, active):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE bundles SET name=?, description=?, required_qty=?, price=?, active=? WHERE id=?",
            (name, description or '', required_qty, price, 1 if active else 0, bundle_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_eligible(bundle_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM bundle_eligible WHERE bundle_id=? ORDER BY description",
            (bundle_id,)
        ).fetchall()
    finally:
        conn.close()


def add_eligible(bundle_id, barcode, description, unit_qty=1):
    """Insert a bundle eligible row and return its id."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO bundle_eligible (bundle_id, barcode, description, unit_qty) VALUES (?,?,?,?)",
            (bundle_id, barcode, description or '', int(unit_qty) if unit_qty else 1)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_eligible_unit_qty(eligible_id, unit_qty):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE bundle_eligible SET unit_qty=? WHERE id=?",
            (int(unit_qty) if unit_qty else 1, eligible_id)
        )
        conn.commit()
    finally:
        conn.close()


def remove_eligible(eligible_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM bundle_eligible WHERE id=?", (eligible_id,))
        conn.commit()
    finally:
        conn.close()


def resolve_barcode_description(barcode):
    """Look up a human-readable description for a barcode from products or selling units."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT description FROM products WHERE barcode=?", (barcode,)
        ).fetchone()
        if row:
            return row[0]
        row = conn.execute(
            "SELECT label FROM product_selling_units WHERE barcode=?", (barcode,)
        ).fetchone()
        if row:
            return row[0]
        return ''
    finally:
        conn.close()


def resolve_barcode_unit_qty(barcode):
    """Return unit_qty from product_selling_units if the barcode is a selling unit, else 1."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT unit_qty FROM product_selling_units WHERE barcode=? AND active=1 LIMIT 1",
            (barcode,)
        ).fetchone()
        return int(row['unit_qty']) if row and row['unit_qty'] else 1
    finally:
        conn.close()
