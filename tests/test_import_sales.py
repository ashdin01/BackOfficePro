"""Tests for scripts/import_sales.py."""
import csv
import io
import os
import pytest
from datetime import date

import scripts.import_sales as import_sales


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_csv_row(plu='10001', plu_name='MILK 2L', quantity='5',
                  sales_dollars='12.50', sale_date='08/05/2026',
                  sales_pct='5.00%', sub_group='DAIRY'):
    """Return a 36-element list matching the Atria CSV column layout."""
    row = [''] * 36
    row[import_sales._COL_PLU]           = plu
    row[import_sales._COL_PLU_NAME]      = plu_name
    row[import_sales._COL_WEIGHT]        = '0'
    row[import_sales._COL_NOMINAL]       = '2.50'
    row[import_sales._COL_DISC]          = '0'
    row[import_sales._COL_SALES_PCT]     = sales_pct
    row[import_sales._COL_SALES_DOLLARS] = sales_dollars
    row[import_sales._COL_QUANTITY]      = quantity
    row[import_sales._COL_SUB_GROUP]     = sub_group
    row[import_sales._COL_ROUNDING]      = '0'
    row[import_sales._COL_DATE]          = sale_date
    return row


def _write_csv(tmp_path, rows, filename='sales.csv'):
    """Write header row + given data rows to a temp CSV file."""
    p = tmp_path / filename
    with open(p, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow([f'textBox{i}' for i in range(36)])  # widget-name header
        for row in rows:
            w.writerow(row)
    return str(p)


# ── _parse_date_dmy ───────────────────────────────────────────────────────────

def test_parse_date_dmy_standard():
    assert import_sales._parse_date_dmy('08/05/2026') == '2026-05-08'


def test_parse_date_dmy_strips_whitespace():
    assert import_sales._parse_date_dmy('  01/01/2025  ') == '2025-01-01'


def test_parse_date_dmy_invalid_raises():
    with pytest.raises(ValueError):
        import_sales._parse_date_dmy('2026-05-08')


# ── parse_csv ─────────────────────────────────────────────────────────────────

def test_parse_csv_returns_expected_keys(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row()])
    rows = import_sales.parse_csv(path)
    assert len(rows) == 1
    r = rows[0]
    for key in ('sale_date', 'plu', 'plu_name', 'sub_group',
                'weight_kg', 'quantity', 'nominal_price',
                'discount', 'rounding', 'sales_dollars', 'sales_pct'):
        assert key in r


def test_parse_csv_correct_values(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row(
        plu='10001', plu_name='MILK 2L', quantity='5',
        sales_dollars='12.50', sale_date='08/05/2026', sales_pct='5.00%',
    )])
    rows = import_sales.parse_csv(path)
    r = rows[0]
    assert r['sale_date'] == '2026-05-08'
    assert r['plu'] == '10001'
    assert r['plu_name'] == 'MILK 2L'
    assert r['quantity'] == 5.0
    assert abs(r['sales_dollars'] - 12.50) < 0.001
    assert r['sales_pct'] == 5.0


def test_parse_csv_skips_widget_header(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row()])
    rows = import_sales.parse_csv(path)
    assert len(rows) == 1  # header not counted


def test_parse_csv_skips_short_rows(tmp_path):
    p = tmp_path / 'short.csv'
    with open(p, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow([f'textBox{i}' for i in range(36)])
        w.writerow(['too', 'short'])
    rows = import_sales.parse_csv(str(p))
    assert rows == []


def test_parse_csv_skips_non_digit_plu(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row(plu='NOTAPLU')])
    assert import_sales.parse_csv(path) == []


def test_parse_csv_skips_empty_date(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row(sale_date='')])
    assert import_sales.parse_csv(path) == []


def test_parse_csv_skips_invalid_date_format(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row(sale_date='2026-05-08')])
    assert import_sales.parse_csv(path) == []


def test_parse_csv_multiple_rows(tmp_path):
    path = _write_csv(tmp_path, [
        _make_csv_row(plu='10001'),
        _make_csv_row(plu='10002'),
        _make_csv_row(plu='NOTPLU'),  # skipped
    ])
    rows = import_sales.parse_csv(path)
    assert len(rows) == 2
    assert {r['plu'] for r in rows} == {'10001', '10002'}


def test_parse_csv_sales_pct_without_percent_sign(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row(sales_pct='3.50')])
    rows = import_sales.parse_csv(path)
    assert rows[0]['sales_pct'] == 3.50


def test_parse_csv_plu_name_whitespace_collapsed(tmp_path):
    path = _write_csv(tmp_path, [_make_csv_row(plu_name='MILK   2L  FULL')])
    rows = import_sales.parse_csv(path)
    assert rows[0]['plu_name'] == 'MILK 2L FULL'


# ── _import_rows ──────────────────────────────────────────────────────────────

def test_import_rows_empty_returns_zeros(test_db):
    result = import_sales._import_rows([], source='test')
    assert result == (0, 0, 0)


def test_import_rows_inserts_into_sales_daily(test_db, db_conn):
    rows = [{
        'sale_date': '2026-05-08', 'plu': '10001', 'plu_name': 'MILK 2L',
        'sub_group': 'DAIRY', 'weight_kg': 0.0, 'quantity': 3.0,
        'nominal_price': 2.50, 'discount': 0.0, 'rounding': 0.0,
        'sales_dollars': 7.50, 'sales_pct': 5.0,
    }]
    upserted, _, _ = import_sales._import_rows(rows, source='test')
    assert upserted == 1
    row = db_conn.execute(
        "SELECT * FROM sales_daily WHERE plu='10001'"
    ).fetchone()
    assert row is not None
    assert row['plu_name'] == 'MILK 2L'
    assert row['quantity'] == 3.0


def test_import_rows_reimport_overwrites_not_duplicates(test_db, db_conn):
    row_data = {
        'sale_date': '2026-05-08', 'plu': '10001', 'plu_name': 'MILK 2L',
        'sub_group': 'DAIRY', 'weight_kg': 0.0, 'quantity': 3.0,
        'nominal_price': 2.50, 'discount': 0.0, 'rounding': 0.0,
        'sales_dollars': 7.50, 'sales_pct': 5.0,
    }
    import_sales._import_rows([row_data], source='first')
    row_data['plu_name'] = 'MILK 2L UPDATED'
    row_data['quantity'] = 5.0
    import_sales._import_rows([row_data], source='second')

    rows = db_conn.execute(
        "SELECT * FROM sales_daily WHERE plu='10001'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]['plu_name'] == 'MILK 2L UPDATED'
    assert rows[0]['quantity'] == 5.0


def test_import_rows_unmatched_plu_counted(test_db):
    rows = [{
        'sale_date': '2026-05-08', 'plu': '99999', 'plu_name': 'UNKNOWN',
        'sub_group': '', 'weight_kg': 0.0, 'quantity': 2.0,
        'nominal_price': 1.0, 'discount': 0.0, 'rounding': 0.0,
        'sales_dollars': 2.0, 'sales_pct': 0.0,
    }]
    upserted, movements, unmatched = import_sales._import_rows(rows, source='test')
    assert upserted == 1
    assert movements == 0
    assert unmatched == 1


def test_import_rows_creates_stock_movement_when_plu_mapped(test_db, db_conn, dept_id, supplier_id):
    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, supplier_id,
            sell_price, cost_price, tax_rate, active, unit)
        VALUES ('9300000099999', 'Test Milk', ?, ?, 3.50, 2.00, 10.0, 1, 'EA')
    """, (dept_id, supplier_id))
    db_conn.execute(
        "INSERT INTO plu_barcode_map (plu, barcode) VALUES (?, ?)",
        (12345, '9300000099999')
    )
    db_conn.commit()

    rows = [{
        'sale_date': '2026-05-08', 'plu': '12345', 'plu_name': 'TEST MILK',
        'sub_group': '', 'weight_kg': 0.0, 'quantity': 4.0,
        'nominal_price': 3.50, 'discount': 0.0, 'rounding': 0.0,
        'sales_dollars': 14.0, 'sales_pct': 0.0,
    }]
    _, movements, _ = import_sales._import_rows(rows, source='test')
    assert movements == 1

    mv = db_conn.execute(
        "SELECT * FROM stock_movements WHERE barcode='9300000099999'"
    ).fetchone()
    assert mv is not None
    assert mv['movement_type'] == 'SALE'
    assert mv['quantity'] == -4.0
