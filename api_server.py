"""REST API server for the BackOffice Stocktake Android app.

Run alongside the desktop app:
    python api_server.py [--host 0.0.0.0] [--port 5050]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, send_file
from database.connection import get_connection
from models import stocktake
from models.barcode_alias import resolve as resolve_alias
import models.product as product_model

app = Flask(__name__)


def _row(row):
    return dict(row) if row else None


def _rows(rows):
    return [dict(r) for r in rows]


@app.route("/api/v1/health")
def health():
    return jsonify({"status": "ok", "app": "BackOfficePro"})


@app.route("/api/v1/store")
def get_store():
    """Public store settings — consumed by RetailPOSPro to display store name etc."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT key, value FROM settings "
            "WHERE key IN ('store_name','store_address','store_phone','store_abn','gst_rate')"
        ).fetchall()
        return jsonify({r["key"]: r["value"] or "" for r in rows})
    finally:
        conn.close()


@app.route("/api/v1/departments")
def get_departments():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, code, name FROM departments WHERE active=1 ORDER BY name"
        ).fetchall()
        return jsonify(_rows(rows))
    finally:
        conn.close()


@app.route("/api/v1/products")
def list_products():
    """
    Product list for POS cache sync and search.
    Query params: search (optional), limit (default 200, max 2000), offset (default 0).
    """
    search = request.args.get("search", "").strip()
    try:
        limit  = min(int(request.args.get("limit",  200)), 2000)
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "limit and offset must be integers"}), 400

    if search:
        rows = product_model.search(search, active_only=True, limit=limit, offset=offset)
        return jsonify(_rows(rows))

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
        """, (limit, offset)).fetchall()
        return jsonify(_rows(rows))
    finally:
        conn.close()


@app.route("/api/v1/products/plu/<int:plu>")
def get_product_by_plu(plu):
    """Look up a product by its PLU number."""
    conn = get_connection()
    try:
        # Check the plu_barcode_map table first
        map_row = conn.execute(
            "SELECT barcode FROM plu_barcode_map WHERE plu = ?", (plu,)
        ).fetchone()
        barcode = map_row["barcode"] if map_row else None

        # Fallback: check the plu column on products directly
        if not barcode:
            p_row = conn.execute(
                "SELECT barcode FROM products WHERE plu = ? AND active = 1 LIMIT 1",
                (str(plu),)
            ).fetchone()
            barcode = p_row["barcode"] if p_row else None

        # Fallback: check selling units PLU
        if not barcode:
            su_row = conn.execute(
                "SELECT barcode FROM product_selling_units WHERE plu = ? AND active = 1 LIMIT 1",
                (str(plu),)
            ).fetchone()
            if su_row and su_row["barcode"]:
                # Delegate to get_product() logic via the barcode
                conn.close()
                return get_product(su_row["barcode"])

        if not barcode:
            return jsonify({"error": "Product not found"}), 404

        row = conn.execute(
            """
            SELECT p.barcode, p.plu, p.description, p.sell_price, p.cost_price,
                   p.tax_rate, p.unit, p.brand, d.name AS dept_name,
                   COALESCE(soh.quantity, 0) AS soh_qty
            FROM products p
            LEFT JOIN departments d     ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh ON soh.barcode = p.barcode
            WHERE p.barcode = ? AND p.active = 1
            """,
            (barcode,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Product not found"}), 404
        return jsonify(_row(row))
    finally:
        conn.close()


@app.route("/api/v1/products/<barcode>")
def get_product(barcode):
    resolved = resolve_alias(barcode)
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT p.barcode, p.plu, p.description, p.sell_price, p.cost_price,
                   p.tax_rate, p.unit, p.brand, d.name AS dept_name,
                   COALESCE(soh.quantity, 0) AS soh_qty
            FROM products p
            LEFT JOIN departments d     ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh ON soh.barcode = p.barcode
            WHERE p.barcode = ? AND p.active = 1
            """,
            (resolved,),
        ).fetchone()
        if row:
            return jsonify(_row(row))

        # Check selling units (case, 6-pack, etc.)
        su = conn.execute(
            """
            SELECT su.barcode, su.label, su.unit_qty, su.sell_price,
                   su.plu AS su_plu,
                   p.barcode AS master_barcode, p.plu, p.cost_price,
                   p.tax_rate, p.unit, p.brand, d.name AS dept_name,
                   COALESCE(soh.quantity, 0) AS master_soh
            FROM product_selling_units su
            JOIN products p             ON su.master_barcode = p.barcode
            LEFT JOIN departments d     ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh ON soh.barcode = p.barcode
            WHERE su.barcode = ? AND su.active = 1 AND p.active = 1
            """,
            (resolved,),
        ).fetchone()
        if not su:
            return jsonify({"error": "Product not found"}), 404

        soh_in_units = int(su['master_soh'] // su['unit_qty']) if su['unit_qty'] > 0 else 0
        return jsonify({
            'barcode':        resolved,
            'master_barcode': su['master_barcode'],
            'plu':            su['su_plu'] or su['plu'] or '',
            'description':    su['label'],
            'sell_price':     su['sell_price'],
            'cost_price':     su['cost_price'],
            'tax_rate':       su['tax_rate'],
            'unit':           su['unit'],
            'brand':          su['brand'],
            'dept_name':      su['dept_name'],
            'unit_qty':       su['unit_qty'],
            'soh_qty':        soh_in_units,
        })
    finally:
        conn.close()


@app.route("/api/v1/sessions", methods=["GET"])
def list_sessions():
    return jsonify(_rows(stocktake.get_all_sessions()))


@app.route("/api/v1/sessions", methods=["POST"])
def create_session():
    data = request.get_json(force=True) or {}
    label = str(data.get("label", "")).strip()
    if not label:
        return jsonify({"error": "label required"}), 400
    dept_id = data.get("department_id")
    notes = data.get("notes", "")
    created_by = data.get("created_by", "Android")
    session_id = stocktake.create_session(label, dept_id, notes, created_by)
    return jsonify({"id": session_id}), 201


@app.route("/api/v1/sessions/<int:session_id>", methods=["GET"])
def get_session(session_id):
    row = stocktake.get_session(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_row(row))


@app.route("/api/v1/sessions/<int:session_id>/counts", methods=["GET"])
def list_counts(session_id):
    return jsonify(_rows(stocktake.get_counts(session_id)))


@app.route("/api/v1/sessions/<int:session_id>/counts", methods=["POST"])
def add_count(session_id):
    data = request.get_json(force=True) or {}
    barcode = str(data.get("barcode", "")).strip()
    qty = data.get("qty")
    if not barcode or qty is None:
        return jsonify({"error": "barcode and qty required"}), 400

    resolved = resolve_alias(barcode)
    conn = get_connection()
    try:
        product = conn.execute(
            "SELECT barcode FROM products WHERE barcode=? AND active=1", (resolved,)
        ).fetchone()
        if not product:
            return jsonify({"error": "Product not found"}), 404
    finally:
        conn.close()

    stocktake.upsert_count(session_id, resolved, float(qty))
    return jsonify({"ok": True, "barcode": resolved}), 200


@app.route("/api/v1/sessions/<int:session_id>/counts/<int:count_id>", methods=["DELETE"])
def delete_count(session_id, count_id):
    stocktake.delete_count(count_id)
    return jsonify({"ok": True}), 200


@app.route("/api/v1/products/<barcode>/image")
def get_product_image(barcode):
    """Serve the product image file. Returns 404 if no image exists."""
    from config.settings import DATA_DIR
    img_dir = os.path.join(DATA_DIR, 'images')
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        path = os.path.join(img_dir, f"{barcode}.{ext}")
        if os.path.exists(path):
            mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else f'image/{ext}'
            return send_file(path, mimetype=mime)
    return jsonify({"error": "No image"}), 404


@app.route("/api/v1/products/<barcode>/image", methods=["DELETE"])
def delete_product_image(barcode):
    """Remove a product image (used by BackOfficePro desktop — not RetailPOSPro)."""
    from config.settings import DATA_DIR
    img_dir = os.path.join(DATA_DIR, 'images')
    deleted = False
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        path = os.path.join(img_dir, f"{barcode}.{ext}")
        if os.path.exists(path):
            os.remove(path)
            deleted = True
    return jsonify({"ok": deleted}), 200


@app.route("/api/v1/pos/sale", methods=["POST"])
def record_pos_sale():
    """
    Record a completed POS sale from RetailPOSPro.
    Reduces stock on hand and writes to sales_daily for each line item.

    Expected JSON body:
    {
      "reference":      "POS-001-20260429-0001",
      "sale_date":      "2026-04-29",
      "operator":       "ashley",
      "payment_method": "CASH",
      "subtotal":       7.27,
      "gst_amount":     0.73,
      "total":          7.99,
      "items": [
        {
          "barcode":     "9300605001234",
          "description": "MILK 2L",
          "qty":         1,
          "unit_price":  7.99,
          "line_total":  7.99,
          "tax_rate":    10.0
        }
      ]
    }
    """
    data = request.get_json(force=True) or {}
    reference = str(data.get("reference", "")).strip()
    sale_date  = str(data.get("sale_date",  "")).strip()
    operator   = str(data.get("operator",   "POS")).strip()
    items      = data.get("items", [])

    if not reference or not sale_date or not items:
        return jsonify({"error": "reference, sale_date, and items are required"}), 400

    conn = get_connection()
    try:
        for item in items:
            barcode     = str(item.get("barcode",     "")).strip()
            qty         = float(item.get("qty",        0))
            line_total  = float(item.get("line_total", 0))
            description = str(item.get("description", "")).strip()

            if not barcode or qty <= 0:
                continue

            barcode = resolve_alias(barcode)

            # Selling unit? deduct qty×unit_qty from master barcode
            su = conn.execute(
                "SELECT master_barcode, unit_qty FROM product_selling_units "
                "WHERE barcode = ? AND active = 1",
                (barcode,)
            ).fetchone()
            if su:
                stock_barcode = su['master_barcode']
                stock_qty     = qty * su['unit_qty']
            else:
                stock_barcode = barcode
                stock_qty     = qty

            # Reduce stock on hand
            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (stock_barcode, -stock_qty))

            # Record stock movement
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by)
                VALUES (?, 'SALE', ?, ?, ?, ?)
            """, (stock_barcode, -stock_qty, reference, description, operator))

            # Write to sales_daily (aggregate by PLU per day)
            plu_row = conn.execute(
                "SELECT plu FROM products WHERE barcode = ?", (stock_barcode,)
            ).fetchone()
            plu = (plu_row["plu"] or stock_barcode) if plu_row and plu_row["plu"] else stock_barcode

            conn.execute("""
                INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sale_date, plu) DO UPDATE SET
                    quantity     = quantity     + excluded.quantity,
                    sales_dollars = sales_dollars + excluded.sales_dollars
            """, (sale_date, plu, description, qty, line_total))

        conn.commit()
        return jsonify({"ok": True, "reference": reference}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/v1/bundles")
def list_bundles():
    """Return all active bundles with their eligible item barcodes — consumed by RetailPOSPro."""
    conn = get_connection()
    try:
        bundles = conn.execute(
            "SELECT id, name, description, required_qty, price FROM bundles WHERE active=1 ORDER BY name"
        ).fetchall()
        result = []
        for b in bundles:
            eligible = conn.execute(
                "SELECT barcode, description, unit_qty FROM bundle_eligible WHERE bundle_id=?",
                (b['id'],)
            ).fetchall()
            result.append({
                'id':           b['id'],
                'name':         b['name'],
                'description':  b['description'] or '',
                'required_qty': b['required_qty'],
                'price':        b['price'],
                'eligible':     [{'barcode': e['barcode'], 'description': e['description'], 'unit_qty': int(e['unit_qty'] or 1)} for e in eligible],
            })
        return jsonify(result)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BackOfficePro API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5050, help="Port (default 5050)")
    args = parser.parse_args()
    print(f"BackOfficePro API → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)
