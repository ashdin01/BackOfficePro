"""REST API server for the BackOffice Stocktake Android app.

Run alongside the desktop app:
    python api_server.py [--host 0.0.0.0] [--port 5050]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify
from database.connection import get_connection
from models import stocktake
from models.barcode_alias import resolve as resolve_alias

app = Flask(__name__)


def _row(row):
    return dict(row) if row else None


def _rows(rows):
    return [dict(r) for r in rows]


@app.route("/api/v1/health")
def health():
    return jsonify({"status": "ok", "app": "BackOfficePro"})


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


@app.route("/api/v1/products/<barcode>")
def get_product(barcode):
    resolved = resolve_alias(barcode)
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT p.barcode, p.description, p.sell_price, p.cost_price,
                   p.unit, p.brand, d.name AS dept_name,
                   COALESCE(soh.quantity, 0) AS soh_qty
            FROM products p
            LEFT JOIN departments d     ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh ON soh.barcode = p.barcode
            WHERE p.barcode = ? AND p.active = 1
            """,
            (resolved,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Product not found"}), 404
        return jsonify(_row(row))
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BackOfficePro API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5050, help="Port (default 5050)")
    args = parser.parse_args()
    print(f"BackOfficePro API → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)
