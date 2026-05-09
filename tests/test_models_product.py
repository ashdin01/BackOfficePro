"""Tests for models/product.py."""
import pytest
from database.connection import get_connection
import models.product as product_model


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def group_id(db_conn, dept_id):
    db_conn.execute("""
        INSERT INTO product_groups (department_id, code, name)
        VALUES (?, 'TST', 'Test Group')
    """, (dept_id,))
    db_conn.commit()
    return db_conn.execute(
        "SELECT id FROM product_groups WHERE code='TST'"
    ).fetchone()['id']


def _add_product(db_conn, barcode, description, dept_id, supplier_id,
                 reorder_point=0, reorder_max=0, cost_price=1.0,
                 active=1, pack_qty=1):
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, reorder_point, reorder_max,
             pack_qty, pack_unit, active, unit)
        VALUES (?, ?, ?, ?, 2.00, ?, 10.0, ?, ?, ?, 'EA', ?, 'EA')
    """, (barcode, description, dept_id, supplier_id,
          cost_price, reorder_point, reorder_max, pack_qty, active))
    db_conn.commit()


# ── get_by_barcode ────────────────────────────────────────────────────────────

def test_get_by_barcode_found(test_db, db_conn, dept_id, supplier_id):
    _add_product(db_conn, '1234567890001', 'Widget A', dept_id, supplier_id)
    p = product_model.get_by_barcode('1234567890001')
    assert p is not None
    assert p['description'] == 'Widget A'


def test_get_by_barcode_not_found(test_db):
    assert product_model.get_by_barcode('0000000000000') is None


# ── get_by_barcodes ───────────────────────────────────────────────────────────

def test_get_by_barcodes_returns_dict(test_db, db_conn, dept_id, supplier_id):
    _add_product(db_conn, '1111111111111', 'Product X', dept_id, supplier_id)
    _add_product(db_conn, '2222222222222', 'Product Y', dept_id, supplier_id)
    result = product_model.get_by_barcodes(['1111111111111', '2222222222222'])
    assert '1111111111111' in result
    assert '2222222222222' in result
    assert result['1111111111111']['description'] == 'Product X'


def test_get_by_barcodes_empty_input(test_db):
    assert product_model.get_by_barcodes([]) == {}


def test_get_by_barcodes_missing_barcode_not_in_result(test_db, db_conn, dept_id, supplier_id):
    _add_product(db_conn, '3333333333333', 'Product Z', dept_id, supplier_id)
    result = product_model.get_by_barcodes(['3333333333333', '9999999999999'])
    assert '3333333333333' in result
    assert '9999999999999' not in result


# ── get_all ───────────────────────────────────────────────────────────────────

def test_get_all_active_only(test_db, db_conn, dept_id, supplier_id):
    _add_product(db_conn, '4444444444444', 'Active Product', dept_id, supplier_id, active=1)
    _add_product(db_conn, '5555555555555', 'Inactive Product', dept_id, supplier_id, active=0)
    rows = product_model.get_all(active_only=True)
    descriptions = [r['description'] for r in rows]
    assert 'Active Product' in descriptions
    assert 'Inactive Product' not in descriptions


def test_get_all_includes_inactive(test_db, db_conn, dept_id, supplier_id):
    _add_product(db_conn, '6666666666666', 'Active B', dept_id, supplier_id, active=1)
    _add_product(db_conn, '7777777777777', 'Inactive B', dept_id, supplier_id, active=0)
    rows = product_model.get_all(active_only=False)
    descriptions = [r['description'] for r in rows]
    assert 'Inactive B' in descriptions


# ── add ───────────────────────────────────────────────────────────────────────

def test_add_product(test_db, dept_id, supplier_id):
    product_model.add(
        barcode='8888888888888',
        description='New Product',
        department_id=dept_id,
        supplier_id=supplier_id,
        sell_price=5.00,
        cost_price=3.00,
        tax_rate=10.0,
        reorder_point=10,
        reorder_max=50,
        pack_qty=6,
        pack_unit='CTN',
    )
    p = product_model.get_by_barcode('8888888888888')
    assert p is not None
    assert p['description'] == 'New Product'
    assert float(p['cost_price']) == 3.00
    assert int(p['pack_qty']) == 6
    assert p['pack_unit'] == 'CTN'


# ── search ────────────────────────────────────────────────────────────────────

def test_search_single_word(test_db, db_conn, dept_id, supplier_id):
    _add_product(db_conn, '9111111111111', 'OASIS BEETROOT DIP', dept_id, supplier_id)
    _add_product(db_conn, '9222222222222', 'CORN CHIPS SALTED', dept_id, supplier_id)
    results = product_model.search('OASIS')
    descriptions = [r['description'] for r in results]
    assert 'OASIS BEETROOT DIP' in descriptions
    assert 'CORN CHIPS SALTED' not in descriptions


def test_search_multi_word_all_must_match(test_db, db_conn, dept_id, supplier_id):
    _add_product(db_conn, '9333333333333', 'OASIS GARLIC DIP', dept_id, supplier_id)
    _add_product(db_conn, '9444444444444', 'OASIS BEETROOT DIP', dept_id, supplier_id)
    results = product_model.search('OASIS GARLIC')
    descriptions = [r['description'] for r in results]
    assert 'OASIS GARLIC DIP' in descriptions
    assert 'OASIS BEETROOT DIP' not in descriptions


def test_search_no_results(test_db):
    results = product_model.search('ZZZNOMATCH')
    assert results == []


def test_search_empty_term(test_db):
    assert product_model.search('') == []
