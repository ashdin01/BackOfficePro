"""
One-off reconciliation for the 2026-09-13 manual-import / ATRIA desync.

Background: DailyPLUSales (25).csv was imported manually as the "final" day
sales on the evening of 2026-09-13, using the OLD import_sales.py (commit
before eba9722) which deduplicated stock movements on a fixed per-PLU
reference. ATRIA's overnight auto-import for the same date then ran on that
same OLD code before the fix was installed, correctly overwriting
sales_daily to ATRIA's true final totals but silently skipping the stock
movement for every PLU already covered by the (25) import (the bug fixed in
eba9722) — full movements are only skipped, never created, for a PLU whose
reference already exists, regardless of whether its quantity grew.

Net effect: sales_daily is correct (it always gets overwritten), but stock
was only ever deducted for (25)'s quantities, not the higher final totals.
Simply re-importing the same ATRIA file with the NEW fixed importer will not
close this gap — the fixed importer computes its delta against whatever is
*currently* in sales_daily, which by then already equals the final numbers,
so it sees no change and (correctly, for a normal case) does nothing.

This script instead computes the gap directly: (25)'s baseline quantity per
PLU vs whatever is now stored in sales_daily for that date, and applies the
difference straight to stock. It does not touch sales_daily at all (already
correct) — only stock_movements / stock_on_hand.

Safe to re-run: each applied movement uses a fixed reference per (date,
plu), so a second run skips whatever was already reconciled instead of
double-applying it.

This is a one-time migration tool for this specific transition — not part
of the normal import flow. Fine to delete once the 2026-09-13 gap has been
reconciled on every affected install.

Usage:
    python3 scripts/reconcile_delta.py <baseline.csv> <sale_date YYYY-MM-DD>

Example (run once, after ATRIA's auto-import has landed for that date):
    python3 scripts/reconcile_delta.py "DailyPLUSales (25).csv" 2026-09-13
"""
import os
import sys

if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from database.connection import get_connection
from models.stock_on_hand import clamp_negative_soh
from scripts.import_sales import parse_csv, _resolve_barcode, ensure_tables


def reconcile(baseline_csv_path, sale_date, source="Reconcile 2026-09-13 desync"):
    """
    Compare baseline_csv_path's per-PLU quantities (the import that ran
    before the desync) against whatever sales_daily now holds for sale_date,
    and apply the difference to stock. Returns a dict of counters.
    """
    ensure_tables()
    baseline_rows = parse_csv(baseline_csv_path)
    baseline = {
        r['plu']: r['quantity'] for r in baseline_rows if r['sale_date'] == sale_date
    }

    counts = {'applied': 0, 'already_done': 0, 'no_gap': 0, 'unmatched': 0, 'missing': 0}

    if not baseline:
        print(f"No rows in {baseline_csv_path} match sale_date {sale_date} — nothing to do.")
        return counts

    conn = get_connection()
    try:
        for plu, baseline_qty in baseline.items():
            row = conn.execute(
                "SELECT plu_name, quantity FROM sales_daily WHERE sale_date=? AND plu=?",
                (sale_date, plu)
            ).fetchone()
            if row is None:
                print(f"  WARNING: PLU {plu} not found in sales_daily for {sale_date} — skipping.")
                counts['missing'] += 1
                continue

            current_qty = row['quantity']
            plu_name = row['plu_name']
            gap = current_qty - baseline_qty

            if gap == 0:
                counts['no_gap'] += 1
                continue

            reference = f"SALE-{sale_date}-PLU{plu}-RECONCILE"
            existing = conn.execute(
                "SELECT id FROM stock_movements WHERE reference=?", (reference,)
            ).fetchone()
            if existing:
                counts['already_done'] += 1
                continue

            barcode, unit_qty = _resolve_barcode(conn, plu)
            if not barcode:
                print(f"  UNMATCHED: PLU {plu} ({plu_name}) — gap {gap:+g} units, no barcode mapped.")
                counts['unmatched'] += 1
                continue

            stock_qty = gap * unit_qty
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by)
                VALUES (?, 'SALE', ?, ?, ?, ?)
            """, (barcode, -stock_qty, reference,
                  f"Reconcile: {plu_name} ({gap:+g} units, baseline {baseline_qty:g} -> {current_qty:g})",
                  source))
            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity     = quantity + excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (barcode, -stock_qty))
            clamp_negative_soh(conn, barcode, reference=reference, created_by=source)

            print(f"  Applied: PLU {plu} ({plu_name}) — {baseline_qty:g} -> {current_qty:g}, "
                  f"stock adjusted by {-stock_qty:+g}")
            counts['applied'] += 1

        conn.commit()
    finally:
        conn.release()

    print(f"\nReconciled {sale_date} against {os.path.basename(baseline_csv_path)}:")
    print(f"  Stock movements applied:      {counts['applied']}")
    print(f"  Already reconciled (skipped): {counts['already_done']}")
    print(f"  No gap (already matched):     {counts['no_gap']}")
    print(f"  Unmatched PLUs (no barcode):  {counts['unmatched']}")
    print(f"  Missing from sales_daily:     {counts['missing']}")
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/reconcile_delta.py <baseline.csv> <sale_date YYYY-MM-DD>")
        sys.exit(1)
    reconcile(sys.argv[1], sys.argv[2])
