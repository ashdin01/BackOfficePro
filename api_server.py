"""REST API server for the BackOffice Stocktake Android app.

Run alongside the desktop app:
    python api_server.py [--host 0.0.0.0] [--port 5050]
"""
import argparse
import hmac
import logging
import re
import secrets
import sqlite3
import sys
import os
import threading
import time
from collections import deque
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, g, request, jsonify, send_file
import controllers.settings_controller as settings_ctrl
import controllers.department_controller as department_ctrl
import controllers.product_controller as product_ctrl
import controllers.stocktake_controller as stocktake_ctrl
import controllers.bundle_controller as bundle_ctrl
import controllers.sales_report_controller as sales_ctrl
import controllers.purchase_order_controller as po_ctrl

app = Flask(__name__)

# Routes that do not require authentication (liveness check only)
_AUTH_EXEMPT = {"/api/v1/health"}

# ── Rate limiters (sliding window, per client IP) ────────────────────────────

# /pos/sale — tight limit to prevent runaway POS retries
_SALE_WINDOW = 1.0   # seconds
_SALE_MAX    = 10    # max requests per window
_sale_lock   = threading.Lock()
_sale_clients: dict[str, deque] = {}

# All other authenticated endpoints — permissive, guards against runaway clients
_READ_WINDOW = 10.0  # seconds
_READ_MAX    = 60    # max requests per window
_read_lock   = threading.Lock()
_read_clients: dict[str, deque] = {}


def _rate_ok(clients: dict, lock: threading.Lock, window: float, max_calls: int,
             client_ip: str) -> bool:
    """Sliding-window rate check for a single client IP. Thread-safe."""
    now = time.monotonic()
    with lock:
        times = clients.setdefault(client_ip, deque())
        while times and times[0] < now - window:
            times.popleft()
        if not times:
            del clients[client_ip]
            times = clients.setdefault(client_ip, deque())
        if len(times) >= max_calls:
            return False
        times.append(now)
        return True


def _sale_rate_ok(client_ip: str) -> bool:
    return _rate_ok(_sale_clients, _sale_lock, _SALE_WINDOW, _SALE_MAX, client_ip)


def _read_rate_ok(client_ip: str) -> bool:
    return _rate_ok(_read_clients, _read_lock, _READ_WINDOW, _READ_MAX, client_ip)


_api_key_cache: str = ""
_api_key_lock = threading.Lock()
_api_key_refresh_ts: float = 0.0   # monotonic time of last store re-read on mismatch
_API_KEY_REFRESH_MIN_S = 5.0


def _get_api_key():
    """Return the stored API key, generating one on first use.

    Resolution (keyring primary, settings DB fallback, plaintext migration)
    lives in utils.api_key so the desktop Settings screen resolves the exact
    same key — see that module for why the two must not diverge.
    The resolved key is cached in-process so every request in the same process
    sees the same value without a keyring/DB round-trip.

    Double-checked locking: the fast path (cache hit) reads the str without a
    lock — safe under CPython's GIL. The slow initialization path acquires the
    lock and re-checks, so concurrent threads can't both run the keyring/DB
    migration or both generate a new key.
    """
    global _api_key_cache
    if _api_key_cache:          # fast path — GIL makes str read effectively atomic
        return _api_key_cache

    with _api_key_lock:
        if _api_key_cache:      # re-check: another thread may have initialized while we waited
            return _api_key_cache

        from utils.api_key import resolve_api_key
        key = resolve_api_key()

        _api_key_cache = key
        return key


def _refresh_api_key() -> str:
    """Re-resolve the key from the keyring/DB and update the cache.

    Called when a request presents a key that doesn't match the cache: the key
    may have been regenerated in the desktop Settings screen, which runs in a
    different process and can't invalidate our cache directly. Re-resolving
    here lets a new key take effect without restarting the API server.
    Throttled so a flood of bad keys can't hammer the keyring/DB.
    """
    global _api_key_cache, _api_key_refresh_ts
    with _api_key_lock:
        now = time.monotonic()
        if now - _api_key_refresh_ts < _API_KEY_REFRESH_MIN_S:
            return _api_key_cache
        _api_key_refresh_ts = now

        from utils.api_key import resolve_api_key
        _api_key_cache = resolve_api_key()
        return _api_key_cache


@app.teardown_appcontext
def _close_db_connection(exc):
    if not app.config.get('TESTING'):
        from database.connection import close_thread_connection
        close_thread_connection()


@app.before_request
def _log_request_start():
    """Assign a short request ID and capture start time for duration logging."""
    g.request_id    = secrets.token_hex(4)   # 8-char hex, unique per request
    g.request_start = time.monotonic()


@app.after_request
def _log_response(response):
    duration_ms = (time.monotonic() - getattr(g, 'request_start', time.monotonic())) * 1000
    req_id = getattr(g, 'request_id', '--------')
    response.headers['X-Request-ID'] = req_id
    msg  = "API %s %s -> %d (%.1f ms) [req=%s]"
    args = (request.method, request.path, response.status_code, duration_ms, req_id)
    if response.status_code == 401:
        logging.warning(msg, *args)
    else:
        logging.debug(msg, *args)
    return response


def _err(code: str, message: str, status: int):
    """Return a structured JSON error response with a machine code and human message."""
    return jsonify({"error": code, "message": message}), status


@app.before_request
def _require_api_key():
    if request.path in _AUTH_EXEMPT:
        return
    provided = request.headers.get("X-API-Key", "")
    expected = _get_api_key()
    if provided and not hmac.compare_digest(provided, expected):
        # Key may have been regenerated in the Settings screen (separate
        # process) — re-resolve from the store before rejecting.
        expected = _refresh_api_key()
    if not provided or not hmac.compare_digest(provided, expected):
        return _err("UNAUTHORIZED", "Missing or invalid API key", 401)


@app.before_request
def _setup_audit_context():
    """Tag this thread as an API request so stock movements record their source."""
    if request.path in _AUTH_EXEMPT:
        return
    from database.audit_context import set_context
    set_context('API', 'API')


@app.before_request
def _rate_limit_reads():
    """/pos/sale has its own tighter limiter; apply the general one to everything else."""
    if request.path in _AUTH_EXEMPT:
        return
    if request.endpoint == 'record_pos_sale':
        return
    if not _read_rate_ok(request.remote_addr or ""):
        logging.warning("API read rate limit exceeded [client=%s req=%s]",
                        request.remote_addr, getattr(g, 'request_id', '?'))
        return _err("RATE_LIMIT", "Rate limit exceeded — slow down and retry", 429)


@app.route("/api/v1/health")
def health():
    try:
        from database.connection import get_connection
        conn = get_connection()
        conn.execute("SELECT 1 FROM settings LIMIT 1")
        conn.release()
    except Exception:
        logging.exception("Health check DB query failed")
        return jsonify({"status": "error", "app": "BackOfficePro"}), 503
    return jsonify({"status": "ok", "app": "BackOfficePro"})


@app.route("/api/v1/store")
def get_store():
    """Public store settings — consumed by RetailPOSPro to display store name etc."""
    return jsonify(settings_ctrl.get_store_settings())


@app.route("/api/v1/departments")
def get_departments():
    rows = department_ctrl.get_all(active_only=True)
    return jsonify([{'id': r['id'], 'code': r['code'], 'name': r['name']} for r in rows])


@app.route("/api/v1/departments/<int:dept_id>/groups")
def get_department_groups(dept_id):
    rows = department_ctrl.get_groups_by_department(dept_id, active_only=True)
    return jsonify([{'id': r['id'], 'code': r['code'], 'name': r['name']} for r in rows])


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
        return _err("INVALID_PARAM", "limit and offset must be integers", 400)

    if search:
        rows = product_ctrl.search_products(search, active_only=True, limit=limit, offset=offset)
        return jsonify([dict(r) for r in rows])

    return jsonify(product_ctrl.get_all_for_pos(limit, offset))


@app.route("/api/v1/products/plu/<int:plu>")
def get_product_by_plu(plu):
    """Look up a product by its PLU number."""
    result = product_ctrl.get_product_by_plu(plu)
    if not result:
        return _err("PRODUCT_NOT_FOUND", "Product not found", 404)
    return jsonify(result)


@app.route("/api/v1/products/<barcode>")
def get_product(barcode):
    result = product_ctrl.get_product_for_pos(barcode)
    if not result:
        return _err("PRODUCT_NOT_FOUND", "Product not found", 404)
    return jsonify(result)


@app.route("/api/v1/sessions", methods=["GET"])
def list_sessions():
    return jsonify([dict(r) for r in stocktake_ctrl.get_all_sessions()])


@app.route("/api/v1/sessions", methods=["POST"])
def create_session():
    data = request.get_json(force=True) or {}
    label = str(data.get("label", "")).strip()
    if not label:
        return _err("MISSING_FIELD", "label required", 400)
    dept_id    = data.get("department_id")
    group_id   = data.get("group_id")
    notes      = data.get("notes", "")
    created_by = data.get("created_by", "Android")
    session_id = stocktake_ctrl.create_session(label, dept_id, group_id, notes, created_by)
    return jsonify({"id": session_id}), 201


@app.route("/api/v1/sessions/<int:session_id>", methods=["GET"])
def get_session(session_id):
    row = stocktake_ctrl.get_session(session_id)
    if not row:
        return _err("SESSION_NOT_FOUND", "Session not found", 404)
    return jsonify(dict(row))


@app.route("/api/v1/sessions/<int:session_id>/counts", methods=["GET"])
def list_counts(session_id):
    return jsonify([dict(r) for r in stocktake_ctrl.get_counts(session_id)])


@app.route("/api/v1/sessions/<int:session_id>/counts", methods=["POST"])
def add_count(session_id):
    data    = request.get_json(force=True) or {}
    barcode = str(data.get("barcode", "")).strip()
    qty     = data.get("qty")
    if not barcode or qty is None:
        return _err("MISSING_FIELD", "barcode and qty required", 400)

    try:
        qty = float(qty)
    except (TypeError, ValueError):
        return _err("INVALID_PARAM", "qty must be a number", 400)
    if qty < 0 or qty > 99_999:
        return _err("INVALID_PARAM", "qty must be between 0 and 99999", 400)

    product = product_ctrl.get_product_by_barcode(barcode)
    if not product or not product['active']:
        return _err("PRODUCT_NOT_FOUND", "Product not found", 404)

    stocktake_ctrl.upsert_count(session_id, product['barcode'], qty)
    return jsonify({"ok": True, "barcode": product['barcode']}), 200


@app.route("/api/v1/sessions/<int:session_id>/counts/barcode/<barcode>", methods=["GET"])
def get_count_for_barcode(session_id, barcode):
    qty = stocktake_ctrl.get_count_for_barcode(session_id, barcode)
    return jsonify({"counted_qty": qty}), 200


@app.route("/api/v1/sessions/<int:session_id>/counts/<int:count_id>", methods=["DELETE"])
def delete_count(session_id, count_id):
    stocktake_ctrl.delete_count(count_id)
    return jsonify({"ok": True}), 200


def _safe_barcode(barcode):
    """Return sanitised barcode or None if it contains path-traversal characters."""
    barcode = os.path.basename(barcode)
    if not re.match(r'^[\w\-\.]+$', barcode):
        return None
    return barcode


@app.route("/api/v1/products/<barcode>/image")
def get_product_image(barcode):
    """Serve the product image file. Returns 404 if no image exists."""
    barcode = _safe_barcode(barcode)
    if not barcode:
        return _err("INVALID_BARCODE", "Invalid barcode", 400)
    path = product_ctrl.find_product_image(barcode)
    if not path:
        return _err("NO_IMAGE", "No image for this product", 404)
    ext  = path.rsplit('.', 1)[-1].lower()
    mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else f'image/{ext}'
    return send_file(path, mimetype=mime)


@app.route("/api/v1/products/<barcode>/image", methods=["DELETE"])
def delete_product_image_route(barcode):
    """Remove a product image (used by BackOfficePro desktop — not RetailPOSPro)."""
    barcode = _safe_barcode(barcode)
    if not barcode:
        return _err("INVALID_BARCODE", "Invalid barcode", 400)
    existed = product_ctrl.find_product_image(barcode) is not None
    product_ctrl.delete_product_image(barcode)
    return jsonify({"ok": existed}), 200


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
    if not _sale_rate_ok(request.remote_addr or ""):
        logging.warning("API /pos/sale rate limit exceeded [client=%s req=%s]",
                        request.remote_addr, getattr(g, 'request_id', '?'))
        return _err("RATE_LIMIT", "Rate limit exceeded — slow down and retry", 429)

    data      = request.get_json(force=True) or {}
    reference = str(data.get("reference", "")).strip()
    sale_date = str(data.get("sale_date",  "")).strip()
    operator  = str(data.get("operator",   "POS")).strip()[:64]
    items     = data.get("items", [])

    if not reference or not sale_date or not items:
        return _err("MISSING_FIELD", "reference, sale_date, and items are required", 400)

    try:
        datetime.strptime(sale_date, "%Y-%m-%d")
    except ValueError:
        return _err("INVALID_DATE", "sale_date must be YYYY-MM-DD", 400)

    try:
        is_new = sales_ctrl.record_pos_sale(reference, sale_date, operator, items)
        return jsonify({"ok": True, "reference": reference, "duplicate": not is_new}), 200
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            logging.warning("POST /pos/sale DB locked [ref=%s req=%s]: %s",
                            reference, getattr(g, 'request_id', '?'), e)
            return _err("DB_LOCKED", "Database busy — retry shortly", 503)
        logging.exception("POST /pos/sale DB error [ref=%s req=%s]",
                          reference, getattr(g, 'request_id', '?'))
        return _err("SALE_ERROR", "Sale could not be recorded", 500)
    except Exception:
        logging.exception("POST /pos/sale failed [ref=%s req=%s]",
                          reference, getattr(g, 'request_id', '?'))
        return _err("SALE_ERROR", "Sale could not be recorded — try again", 500)


@app.route("/api/v1/bundles")
def list_bundles():
    """Return all active bundles with their eligible item barcodes — consumed by RetailPOSPro."""
    bundles = bundle_ctrl.get_all(active_only=True)
    result  = []
    for b in bundles:
        eligible = bundle_ctrl.get_eligible(b['id'])
        result.append({
            'id':           b['id'],
            'name':         b['name'],
            'description':  b['description'] or '',
            'required_qty': b['required_qty'],
            'price':        b['price'],
            'eligible':     [
                {'barcode': e['barcode'], 'description': e['description'],
                 'unit_qty': int(e['unit_qty'] or 1)}
                for e in eligible
            ],
        })
    return jsonify(result)


# ── Purchase Order receiving ──────────────────────────────────────────────────

@app.route("/api/v1/purchase-orders", methods=["GET"])
def list_purchase_orders():
    """Return SENT and PARTIAL POs with line counts — for the mobile receive app."""
    rows = po_ctrl.get_receivable_pos()
    return jsonify([{
        'id':            r['id'],
        'po_number':     r['po_number'],
        'supplier_name': r['supplier_name'],
        'status':        r['status'],
        'delivery_date': r['delivery_date'] or '',
        'created_at':    r['created_at'],
        'line_count':    r['line_count'],
    } for r in rows])


@app.route("/api/v1/purchase-orders/<po_number>", methods=["GET"])
def get_purchase_order(po_number):
    """Return a PO and its product lines (note lines excluded), looked up by PO number."""
    po = po_ctrl.get_po_by_number(po_number)
    if not po:
        return _err("NOT_FOUND", f"Purchase order '{po_number}' not found", 404)

    raw_lines = [l for l in po_ctrl.get_po_lines(po['id']) if not l['is_note']]
    lines = []
    for l in raw_lines:
        pack_qty = max(1, int(l['pack_qty'] or 1))
        lines.append({
            'id':            l['id'],
            'barcode':       l['barcode'],
            'description':   l['description'],
            'ordered_qty':   l['ordered_qty'],
            'pack_qty':      pack_qty,
            'ordered_units': int((l['ordered_qty'] or 0) * pack_qty),
            'received_qty':  l['received_qty'] or 0,
            'unit_cost':     l['unit_cost'] or 0,
        })

    return jsonify({
        'id':             po['id'],
        'po_number':      po['po_number'],
        'supplier_name':  po['supplier_name'],
        'status':         po['status'],
        'delivery_date':  po['delivery_date'] or '',
        'created_at':     po['created_at'],
        'invoice_number': po.get('supplier_invoice_number') or '',
        'notes':          po['notes'] or '',
        'lines':          lines,
    })


@app.route("/api/v1/purchase-orders/<int:po_id>/receive", methods=["POST"])
def receive_purchase_order(po_id):
    """
    Submit a PO receipt from the mobile app.

    Body:
        invoice_number  str   optional supplier invoice number
        lines           list  [{line_id: int, received_qty: float}, ...]

    received_qty is in cartons (matching ordered_qty units on the PO line).
    Lines with received_qty=0 or omitted are left unchanged.
    final_status is RECEIVED when every product line is now covered (received
    in this call or already received from a prior partial receipt); PARTIAL otherwise.
    """
    po = po_ctrl.get_po_by_id(po_id)
    if not po:
        return _err("NOT_FOUND", "Purchase order not found", 404)
    if po['status'] not in ('SENT', 'PARTIAL'):
        return _err("INVALID_STATUS",
                    f"PO {po['po_number']} cannot be received (status: {po['status']})", 409)

    body = request.get_json(silent=True) or {}
    invoice_number = str(body.get('invoice_number') or '').strip()[:100]
    submitted = body.get('lines')
    if not isinstance(submitted, list) or not submitted:
        return _err("BAD_REQUEST", "'lines' must be a non-empty list", 400)

    # Load all product lines for this PO (note lines excluded), keyed by id
    all_lines = {l['id']: l for l in po_ctrl.get_po_lines(po_id)
                 if not l['is_note']}
    if not all_lines:
        return _err("BAD_REQUEST", "PO has no product lines", 400)

    line_receipts = []
    seen_ids = set()
    for item in submitted:
        line_id = item.get('line_id')
        if not isinstance(line_id, int):
            return _err("BAD_REQUEST",
                        f"line_id must be an integer, got {line_id!r}", 400)
        if line_id not in all_lines:
            return _err("BAD_REQUEST",
                        f"line_id {line_id} does not belong to PO {po_id}", 400)
        if line_id in seen_ids:
            return _err("BAD_REQUEST", f"Duplicate line_id: {line_id}", 400)
        seen_ids.add(line_id)

        try:
            received_qty = float(item['received_qty'])
        except (TypeError, ValueError, KeyError):
            return _err("BAD_REQUEST",
                        f"line_id {line_id}: received_qty must be a number", 400)
        if received_qty < 0:
            return _err("BAD_REQUEST",
                        f"line_id {line_id}: received_qty cannot be negative", 400)

        if received_qty == 0:
            continue  # nothing received for this line in this call

        line = all_lines[line_id]
        pack_qty = max(1, int(line['pack_qty'] or 1))
        line_receipts.append({
            'line_id':          line_id,
            'barcode':          line['barcode'],
            'new_received_qty': received_qty,
            'actual_cost':      None,   # preserve existing cost; adjust on desktop if needed
            'unit_cost':        None,
            'is_promo':         False,
            'qty_units':        received_qty * pack_qty,
        })

    if not line_receipts:
        return _err("BAD_REQUEST", "No lines have received_qty > 0", 400)

    # RECEIVED when every product line is covered after this call
    already_received = {lid for lid, l in all_lines.items()
                        if (l['received_qty'] or 0) > 0}
    now_received     = {r['line_id'] for r in line_receipts}
    final_status = 'RECEIVED' if (already_received | now_received) >= set(all_lines) \
                   else 'PARTIAL'

    try:
        po_ctrl.receive_po_atomic(po_id, po['po_number'], line_receipts, final_status,
                                  supplier_invoice_number=invoice_number)
    except Exception as e:
        logging.exception("PO receive failed po_id=%s", po_id)
        return _err("RECEIVE_FAILED", str(e), 500)

    return jsonify({
        'po_number':      po['po_number'],
        'status':         final_status,
        'lines_received': len(line_receipts),
    }), 200


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BackOfficePro API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5050, help="Port (default 5050)")
    parser.add_argument("--threads", type=int, default=4,
                        help="Waitress worker threads (default 4)")
    parser.add_argument("--no-tls", action="store_true",
                        help="Serve plain HTTP instead of HTTPS (not recommended)")
    args = parser.parse_args()
    _get_api_key()
    if args.no_tls:
        from waitress import serve as _waitress_serve
        print(f"BackOfficePro API -> http://{args.host}:{args.port}  (TLS disabled)")
        print("API key loaded from keyring/DB. Pass as header: X-API-Key: <key>")
        _waitress_serve(app, host=args.host, port=args.port, threads=args.threads)
    else:
        from utils.tls import serve_tls
        serve_tls(app, host=args.host, port=args.port, threads=args.threads)
