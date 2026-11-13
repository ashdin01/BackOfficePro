"""Warehouse Order: warehouse -> shop stock transfer prepared on the phone.

Not a purchase order. Nothing is stored in the database; the submitted order
is written out as a CSV and a print-friendly PDF on the PC running the API.
"""
import csv
import os
from datetime import datetime

from database.connection import db_conn
import controllers.settings_controller as settings_ctrl

OUTPUT_DIR_SETTING = "warehouse_order_output_dir"
MAX_QTY = 99_999


def get_items() -> list:
    """Active products flagged warehouse_order_include, with shop SOH."""
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT p.barcode, p.description, p.unit, p.carton_sku,
                   COALESCE(soh.quantity, 0) AS on_hand
            FROM products p
            LEFT JOIN stock_on_hand soh ON p.barcode = soh.barcode
            WHERE p.active = 1 AND p.warehouse_order_include = 1
            ORDER BY p.description
        """).fetchall()
        return [dict(r) for r in rows]


def output_dir() -> str:
    """Configured output folder, else the user's Downloads folder."""
    configured = settings_ctrl.get_setting(OUTPUT_DIR_SETTING, '').strip()
    return configured or os.path.join(os.path.expanduser("~"), "Downloads")


def validate_lines(lines) -> list:
    """Return merged [{barcode, description, qty}]; raise ValueError on bad input."""
    if not isinstance(lines, list) or not lines:
        raise ValueError("'lines' must be a non-empty list")
    allowed = {i['barcode']: i for i in get_items()}
    merged = {}
    for entry in lines:
        if not isinstance(entry, dict) or not entry.get("barcode") or "qty" not in entry:
            raise ValueError("each line needs barcode and qty")
        barcode = str(entry["barcode"]).strip()
        try:
            qty = float(entry["qty"])
        except (TypeError, ValueError):
            raise ValueError(f"invalid qty for {barcode}")
        if qty != qty or qty <= 0 or qty > MAX_QTY:
            raise ValueError(f"qty for {barcode} must be between 0 and {MAX_QTY}")
        if barcode not in allowed:
            raise ValueError(f"{barcode} is not on the Warehouse Order list")
        merged[barcode] = merged.get(barcode, 0.0) + qty
    return [{"barcode": b, "description": allowed[b]["description"], "qty": q}
            for b, q in merged.items()]


def write_order_files(lines: list, notes: str = "", now=None, out_dir: str = None) -> dict:
    """Write CSV + PDF; return {'csv': path, 'pdf': path}. Raises OSError on failure."""
    from utils.warehouse_order_pdf import build_warehouse_order_pdf
    now = now or datetime.now()
    out_dir = out_dir or output_dir()
    os.makedirs(out_dir, exist_ok=True)
    stem = f"WarehouseOrder_{now:%Y-%m-%d_%H%M}"
    csv_path = os.path.join(out_dir, stem + ".csv")
    pdf_path = os.path.join(out_dir, stem + ".pdf")
    n = 2
    while os.path.exists(csv_path) or os.path.exists(pdf_path):   # same-minute resend
        csv_path = os.path.join(out_dir, f"{stem}_{n}.csv")
        pdf_path = os.path.join(out_dir, f"{stem}_{n}.pdf")
        n += 1

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Barcode", "Product Description", "Order Qty"])
        for ln in lines:
            q = ln["qty"]
            w.writerow([ln["barcode"], ln["description"], int(q) if q == int(q) else q])
    store = settings_ctrl.get_setting("store_name", '')
    details = []
    for key, fmt in (("store_address", "{}"), ("store_phone", "Ph: {}"), ("store_abn", "ABN: {}")):
        val = settings_ctrl.get_setting(key, '')
        if val:
            details.append(fmt.format(val))
    build_warehouse_order_pdf(pdf_path, lines, now, store_name=store, notes=notes,
                              store_details=" | ".join(details))
    return {"csv": csv_path, "pdf": pdf_path}
