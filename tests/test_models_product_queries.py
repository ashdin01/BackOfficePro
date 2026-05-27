"""Tests for models/product_queries.py (split from models/product.py in v7 refactor)."""
import pytest
import models.product_queries as pq_model


@pytest.fixture()
def reorder_product(db_conn, dept_id, supplier_id):
    """Product with SOH below reorder point, linked via product_suppliers."""
    bc = 'REORDER001'
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit,
             active, unit, reorder_point, reorder_max)
        VALUES (?, 'Reorder Me', ?, ?, 2.00, 1.00, 10, 6, 'EA', 1, 'EA', 12, 24)
    """, (bc, dept_id, supplier_id))
    db_conn.execute("""
        INSERT OR IGNORE INTO stock_on_hand (barcode, quantity) VALUES (?, 5)
    """, (bc,))
    db_conn.execute("""
        INSERT OR IGNORE INTO product_suppliers (barcode, supplier_id, is_default)
        VALUES (?, ?, 1)
    """, (bc, supplier_id))
    db_conn.commit()
    return bc


class TestGetReorderCandidates:
    def test_empty_when_no_qualifying_products(self, test_db, supplier_id):
        assert pq_model.get_reorder_candidates(supplier_id) == []

    def test_returns_product_below_reorder_point(self, test_db, supplier_id, reorder_product):
        rows = pq_model.get_reorder_candidates(supplier_id)
        barcodes = [r['barcode'] for r in rows]
        assert reorder_product in barcodes

    def test_excludes_product_above_reorder_point(self, test_db, db_conn, supplier_id, reorder_product):
        db_conn.execute(
            "UPDATE stock_on_hand SET quantity=50 WHERE barcode=?", (reorder_product,)
        )
        db_conn.commit()
        assert pq_model.get_reorder_candidates(supplier_id) == []

    def test_row_has_required_fields(self, test_db, supplier_id, reorder_product):
        row = pq_model.get_reorder_candidates(supplier_id)[0]
        for field in ('barcode', 'description', 'reorder_point', 'reorder_max',
                      'cost_price', 'on_hand', 'pack_qty', 'pack_unit'):
            assert field in dict(row), f"missing field: {field}"


class TestGetItemsForSupplier:
    def test_returns_all_active_when_no_supplier(self, test_db, product_barcode):
        rows = pq_model.get_items_for_supplier(supplier_id=None)
        barcodes = [r['barcode'] for r in rows]
        assert product_barcode in barcodes

    def test_filters_by_supplier_via_junction(self, test_db, db_conn,
                                              supplier_id, product_barcode):
        db_conn.execute("""
            INSERT OR IGNORE INTO product_suppliers (barcode, supplier_id, is_default)
            VALUES (?, ?, 1)
        """, (product_barcode, supplier_id))
        db_conn.commit()
        rows = pq_model.get_items_for_supplier(supplier_id=supplier_id)
        assert any(r['barcode'] == product_barcode for r in rows)

    def test_row_has_required_fields(self, test_db, product_barcode):
        rows = pq_model.get_items_for_supplier(supplier_id=None)
        row = next(r for r in rows if r['barcode'] == product_barcode)
        for field in ('barcode', 'description', 'pack_qty', 'pack_unit', 'cost_price'):
            assert field in dict(row)


class TestGetWithSoh:
    def test_returns_none_for_unknown_barcode(self, test_db):
        assert pq_model.get_with_soh('0000000000') is None

    def test_returns_none_for_inactive_product(self, test_db, db_conn, product_barcode):
        db_conn.execute("UPDATE products SET active=0 WHERE barcode=?", (product_barcode,))
        db_conn.commit()
        assert pq_model.get_with_soh(product_barcode) is None

    def test_returns_dict_with_soh_for_active_product(self, test_db, product_barcode):
        result = pq_model.get_with_soh(product_barcode)
        assert result is not None
        assert result['barcode'] == product_barcode
        assert 'soh_qty' in result

    def test_soh_qty_zero_when_no_stock(self, test_db, product_barcode):
        result = pq_model.get_with_soh(product_barcode)
        assert result['soh_qty'] == 0


class TestGetAllForPos:
    def test_returns_list(self, test_db):
        assert isinstance(pq_model.get_all_for_pos(), list)

    def test_includes_active_product(self, test_db, product_barcode):
        rows = pq_model.get_all_for_pos()
        barcodes = [r['barcode'] for r in rows]
        assert product_barcode in barcodes

    def test_excludes_inactive_product(self, test_db, db_conn, product_barcode):
        db_conn.execute("UPDATE products SET active=0 WHERE barcode=?", (product_barcode,))
        db_conn.commit()
        rows = pq_model.get_all_for_pos()
        assert not any(r['barcode'] == product_barcode for r in rows)

    def test_limit_and_offset(self, test_db, product_barcode):
        rows = pq_model.get_all_for_pos(limit=1, offset=0)
        assert len(rows) <= 1
