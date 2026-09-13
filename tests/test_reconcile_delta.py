"""Tests for scripts/reconcile_delta.py.

Simulates the exact desync it's meant to fix: sales_daily already holds a
higher "final" quantity (as if ATRIA's overnight auto-import already ran on
the old, unfixed import_sales.py), but stock_movements only reflects the
lower baseline quantity from the manual import that preceded it — no
movement was ever created for the difference.
"""
import csv
import os
import pytest

import scripts.import_sales as import_sales
import scripts.reconcile_delta as reconcile_delta
import models.stock_on_hand as soh_model


def _write_baseline_csv(tmp_path, rows, filename='baseline.csv'):
    p = tmp_path / filename
    with open(p, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow([f'textBox{i}' for i in range(36)])
        for row in rows:
            w.writerow(row)
    return str(p)


def _make_row(plu, quantity, sale_date='13/09/2026', plu_name='TEST ITEM'):
    row = [''] * 36
    row[import_sales._COL_PLU]           = plu
    row[import_sales._COL_PLU_NAME]      = plu_name
    row[import_sales._COL_WEIGHT]        = '0'
    row[import_sales._COL_NOMINAL]       = '2.50'
    row[import_sales._COL_DISC]          = '0'
    row[import_sales._COL_SALES_PCT]     = '5.00%'
    row[import_sales._COL_SALES_DOLLARS] = '12.50'
    row[import_sales._COL_QUANTITY]      = str(quantity)
    row[import_sales._COL_SUB_GROUP]     = 'GROCERY'
    row[import_sales._COL_ROUNDING]      = '0'
    row[import_sales._COL_DATE]          = sale_date
    return row


@pytest.fixture()
def desynced_plu(db_conn, dept_id, supplier_id):
    """A product sold both in the original manual import (baseline_qty=5)
    and, per the later ATRIA auto-import, up to a higher final total
    (current_qty=8) — but with only the baseline quantity ever deducted
    from stock, mirroring the old code's skipped-movement bug."""
    bc = '9300000055555'
    plu = '77777'
    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, supplier_id,
            sell_price, cost_price, tax_rate, active, unit)
        VALUES (?, 'Test Desync Item', ?, ?, 3.50, 2.00, 10.0, 1, 'EA')
    """, (bc, dept_id, supplier_id))
    db_conn.execute("INSERT INTO plu_barcode_map (plu, barcode) VALUES (?, ?)", (77777, bc))

    # sales_daily already holds the higher "final" quantity (as ATRIA's old-code
    # overnight import would have overwritten it to).
    db_conn.execute("""
        INSERT INTO sales_daily
            (sale_date, plu, plu_name, sub_group, weight_kg, quantity,
             nominal_price, discount, rounding, sales_dollars, sales_pct)
        VALUES ('2026-09-13', ?, 'TEST ITEM', 'GROCERY', 0, 8, 2.50, 0, 0, 20.0, 5.0)
    """, (plu,))

    # But stock was only ever deducted for the original baseline quantity (5),
    # via the old-style (unversioned) reference the pre-fix code used.
    db_conn.execute("""
        INSERT INTO stock_movements (barcode, movement_type, quantity, reference, notes, created_by)
        VALUES (?, 'SALE', -5, 'SALE-2026-09-13-PLU77777', 'Sale: TEST ITEM (5 units)', 'CSV Import')
    """, (bc,))
    db_conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, -5)
        ON CONFLICT(barcode) DO UPDATE SET quantity = quantity + excluded.quantity
    """, (bc,))
    db_conn.commit()
    return bc, plu


def test_reconcile_applies_missing_gap(test_db, db_conn, desynced_plu, tmp_path):
    bc, plu = desynced_plu
    baseline_path = _write_baseline_csv(tmp_path, [_make_row(plu, quantity=5)])

    counts = reconcile_delta.reconcile(baseline_path, '2026-09-13')

    assert counts['applied'] == 1
    soh = soh_model.get_by_barcode(bc)
    assert soh['quantity'] == pytest.approx(-8.0)  # now matches sales_daily's final qty=8

    moves = db_conn.execute(
        "SELECT movement_type, quantity, reference FROM stock_movements"
        " WHERE barcode=? ORDER BY id", (bc,)
    ).fetchall()
    assert [(m['movement_type'], m['quantity']) for m in moves] == [
        ('SALE', -5.0), ('SALE', -3.0),
    ]
    assert moves[1]['reference'] == 'SALE-2026-09-13-PLU77777-RECONCILE'


def test_reconcile_is_idempotent(test_db, db_conn, desynced_plu, tmp_path):
    bc, plu = desynced_plu
    baseline_path = _write_baseline_csv(tmp_path, [_make_row(plu, quantity=5)])

    reconcile_delta.reconcile(baseline_path, '2026-09-13')
    counts = reconcile_delta.reconcile(baseline_path, '2026-09-13')

    assert counts['applied'] == 0
    assert counts['already_done'] == 1
    soh = soh_model.get_by_barcode(bc)
    assert soh['quantity'] == pytest.approx(-8.0)  # unchanged by the second run


def test_reconcile_no_gap_is_skipped(test_db, db_conn, desynced_plu, tmp_path):
    bc, plu = desynced_plu
    # Baseline already matches sales_daily's current quantity (8) — no gap.
    baseline_path = _write_baseline_csv(tmp_path, [_make_row(plu, quantity=8)])

    counts = reconcile_delta.reconcile(baseline_path, '2026-09-13')

    assert counts['applied'] == 0
    assert counts['no_gap'] == 1
    soh = soh_model.get_by_barcode(bc)
    assert soh['quantity'] == pytest.approx(-5.0)  # untouched


def test_reconcile_unmatched_plu_counted(test_db, db_conn, tmp_path):
    db_conn.execute("""
        INSERT INTO sales_daily
            (sale_date, plu, plu_name, sub_group, weight_kg, quantity,
             nominal_price, discount, rounding, sales_dollars, sales_pct)
        VALUES ('2026-09-13', '88888', 'GHOST ITEM', 'GROCERY', 0, 4, 2.50, 0, 0, 10.0, 1.0)
    """)
    db_conn.commit()
    baseline_path = _write_baseline_csv(tmp_path, [_make_row('88888', quantity=2)])

    counts = reconcile_delta.reconcile(baseline_path, '2026-09-13')

    assert counts['applied'] == 0
    assert counts['unmatched'] == 1


def test_reconcile_wrong_date_finds_nothing(test_db, db_conn, desynced_plu, tmp_path):
    bc, plu = desynced_plu
    baseline_path = _write_baseline_csv(tmp_path, [_make_row(plu, quantity=5, sale_date='14/09/2026')])

    counts = reconcile_delta.reconcile(baseline_path, '2026-09-13')

    assert counts == {'applied': 0, 'already_done': 0, 'no_gap': 0, 'unmatched': 0, 'missing': 0}
