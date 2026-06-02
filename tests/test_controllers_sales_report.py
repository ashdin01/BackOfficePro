"""Tests for controllers/sales_report_controller.py — DB-backed tests."""
import pytest
from datetime import date, timedelta
import controllers.sales_report_controller as sr_ctrl


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990001',
                    description='Sale Product', plu='9001'):
    db_conn.execute("""
        INSERT INTO products
            (barcode, plu, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, ?, ?, ?, ?, 5.00, 2.50, 10.0, 1, 'EA', 1, 'EA')
    """, (barcode, plu, description, dept_id, supplier_id))
    db_conn.commit()
    return barcode


def _record_sale(reference, sale_date, items, operator='op1'):
    return sr_ctrl.record_pos_sale(reference, sale_date, operator, items)


# ── record_pos_sale ───────────────────────────────────────────────────────────

class TestRecordPosSale:
    def test_returns_true_for_new_sale(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id)
        result = _record_sale('REF001', '2026-05-01',
                              [{'barcode': bc, 'qty': 2, 'line_total': 10.00,
                                'description': 'Sale Product'}])
        assert result is True

    def test_reduces_soh_by_qty_sold(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990010')
        # Set initial SOH
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, 20)",
            (bc,)
        )
        db_conn.commit()
        _record_sale('REF002', '2026-05-01',
                     [{'barcode': bc, 'qty': 5, 'line_total': 25.00, 'description': 'P'}])
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (bc,)
        ).fetchone()
        assert row['quantity'] == 15

    def test_creates_sale_movement(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990011')
        _record_sale('REF003', '2026-05-02',
                     [{'barcode': bc, 'qty': 3, 'line_total': 15.00, 'description': 'P'}])
        row = db_conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=? AND movement_type='SALE'",
            (bc,)
        ).fetchone()
        assert row is not None
        assert row['quantity'] == -3

    def test_upserts_sales_daily(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id,
                             barcode='9300099990012', plu='9002')
        _record_sale('REF004', '2026-05-03',
                     [{'barcode': bc, 'qty': 4, 'line_total': 20.00, 'description': 'P'}])
        row = db_conn.execute(
            "SELECT quantity FROM sales_daily WHERE plu=? AND sale_date='2026-05-03'",
            ('9002',)
        ).fetchone()
        assert row is not None
        assert row['quantity'] == 4

    def test_duplicate_reference_returns_false(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990013')
        items = [{'barcode': bc, 'qty': 1, 'line_total': 5.00, 'description': 'P'}]
        _record_sale('REF005', '2026-05-04', items)
        result = _record_sale('REF005', '2026-05-04', items)
        assert result is False

    def test_duplicate_does_not_double_reduce_soh(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990014')
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, 10)", (bc,)
        )
        db_conn.commit()
        items = [{'barcode': bc, 'qty': 2, 'line_total': 10.00, 'description': 'P'}]
        _record_sale('REF006', '2026-05-05', items)
        _record_sale('REF006', '2026-05-05', items)  # second call is ignored
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (bc,)
        ).fetchone()
        # SOH should only be reduced once (10 - 2 = 8)
        assert row['quantity'] == 8

    def test_invalid_sale_date_raises(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990015')
        with pytest.raises(ValueError):
            _record_sale('REF007', 'not-a-date',
                         [{'barcode': bc, 'qty': 1, 'line_total': 5.00, 'description': 'P'}])

    def test_skips_items_with_zero_qty(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990016')
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, 10)", (bc,)
        )
        db_conn.commit()
        # qty=0 should be silently skipped
        _record_sale('REF008', '2026-05-06',
                     [{'barcode': bc, 'qty': 0, 'line_total': 0.00, 'description': 'P'}])
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (bc,)
        ).fetchone()
        # SOH unchanged
        assert row['quantity'] == 10

    def test_skips_items_with_empty_barcode(self, test_db, db_conn, dept_id, supplier_id):
        # Should not raise — empty barcode items are skipped
        result = _record_sale('REF009', '2026-05-07',
                              [{'barcode': '', 'qty': 2, 'line_total': 10.00, 'description': 'P'}])
        assert result is True

    def test_alias_resolved_to_master(self, test_db, db_conn, dept_id, supplier_id):
        master_bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990020')
        alias_bc = '9300099990021'
        db_conn.execute(
            "INSERT INTO barcode_aliases (alias_barcode, master_barcode) VALUES (?, ?)",
            (alias_bc, master_bc)
        )
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, 10)", (master_bc,)
        )
        db_conn.commit()
        _record_sale('REF010', '2026-05-08',
                     [{'barcode': alias_bc, 'qty': 3, 'line_total': 15.00, 'description': 'P'}])
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (master_bc,)
        ).fetchone()
        # Alias resolved — master SOH reduced
        assert row['quantity'] == 7


# ── barcode_exists ────────────────────────────────────────────────────────────

class TestBarcodeExists:
    def test_existing_barcode_returns_true(self, test_db, product_barcode):
        assert sr_ctrl.barcode_exists(product_barcode) is True

    def test_missing_barcode_returns_false(self, test_db, db_conn, dept_id, supplier_id):
        assert sr_ctrl.barcode_exists('0000000000000') is False


# ── sales_table_exists ────────────────────────────────────────────────────────

def test_sales_table_exists_returns_true(test_db):
    assert sr_ctrl.sales_table_exists() is True


# ── PLU map ───────────────────────────────────────────────────────────────────

class TestPluMap:
    def test_save_and_load_plu_map(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990030', plu='5001')
        sr_ctrl.save_plu_map(5001, bc)
        plu_map = sr_ctrl.load_plu_map()
        assert 5001 in plu_map
        assert plu_map[5001] == bc

    def test_save_plu_map_invalid_plu_is_ignored(self, test_db, db_conn, dept_id, supplier_id):
        # Non-integer PLU should not raise
        bc = _insert_product(db_conn, dept_id, supplier_id, barcode='9300099990031')
        sr_ctrl.save_plu_map('not-a-number', bc)
        plu_map = sr_ctrl.load_plu_map()
        # Nothing was stored for the bad PLU
        assert 'not-a-number' not in plu_map


# ── Sales aggregate queries ───────────────────────────────────────────────────

class TestSalesAggregates:
    def _insert_daily_sales(self, db_conn, sale_date, plu='7001', qty=10, dollars=50.0):
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
            VALUES (?, ?, 'Test Product', ?, ?)
        """, (sale_date, plu, qty, dollars))
        db_conn.commit()

    def test_get_sales_stats_returns_totals(self, test_db, db_conn):
        self._insert_daily_sales(db_conn, '2026-04-01', qty=10, dollars=50.0)
        self._insert_daily_sales(db_conn, '2026-04-02', qty=5, dollars=25.0)
        stats = sr_ctrl.get_sales_stats('2026-04-01', '2026-04-02')
        assert stats['total_qty'] == 15
        assert stats['total_days'] == 2

    def test_get_sales_by_product_aggregates_by_plu(self, test_db, db_conn):
        self._insert_daily_sales(db_conn, '2026-04-01', plu='8001', qty=6)
        self._insert_daily_sales(db_conn, '2026-04-02', plu='8001', qty=4)
        rows = sr_ctrl.get_sales_by_product('2026-04-01', '2026-04-02')
        totals = {r['plu']: r['qty'] for r in rows}
        assert totals.get('8001') == 10

    def test_get_sales_by_day_returns_per_date(self, test_db, db_conn):
        self._insert_daily_sales(db_conn, '2026-04-10', qty=7)
        self._insert_daily_sales(db_conn, '2026-04-11', qty=3)
        rows = sr_ctrl.get_sales_by_day('2026-04-10', '2026-04-11')
        dates = {r['sale_date']: r['quantity'] for r in rows}
        assert dates.get('2026-04-10') == 7
        assert dates.get('2026-04-11') == 3

    def test_get_sales_by_group_aggregates(self, test_db, db_conn):
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, sub_group, quantity, sales_dollars)
            VALUES ('2026-04-15', '6001', 'Prod A', 'GROC', 5, 20.0)
        """)
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, sub_group, quantity, sales_dollars)
            VALUES ('2026-04-15', '6002', 'Prod B', 'DAIRY', 3, 12.0)
        """)
        db_conn.commit()
        rows = sr_ctrl.get_sales_by_group('2026-04-15', '2026-04-15')
        groups = {r['sub_group']: r['quantity'] for r in rows}
        assert groups.get('GROC') == 5
        assert groups.get('DAIRY') == 3

    def test_get_sales_groups_returns_distinct_sorted(self, test_db, db_conn):
        for grp in ('ZGROUP', 'AGROUP', 'MGROUP'):
            db_conn.execute("""
                INSERT INTO sales_daily (sale_date, plu, plu_name, sub_group, quantity)
                VALUES ('2026-03-01', ?, 'P', ?, 1)
            """, (grp, grp))
        db_conn.commit()
        groups = sr_ctrl.get_sales_groups()
        assert groups == sorted(groups)

    def test_get_sales_stats_empty_range_returns_zeros(self, test_db):
        stats = sr_ctrl.get_sales_stats('2000-01-01', '2000-01-02')
        assert stats['total_qty'] == 0
        assert stats['total_days'] == 0


# ── get_all_products / get_products_with_stock ────────────────────────────────

def test_get_all_products_includes_inserted_product(test_db, product_barcode):
    products = sr_ctrl.get_all_products()
    barcodes = [p['barcode'] for p in products]
    assert product_barcode in barcodes


def test_get_products_with_stock(test_db, product_barcode):
    products = sr_ctrl.get_products_with_stock()
    assert isinstance(products, list)
    barcodes = [p['barcode'] for p in products]
    assert product_barcode in barcodes


def test_ensure_plu_map_table(test_db):
    sr_ctrl.ensure_plu_map_table()


def test_get_departments(test_db):
    depts = sr_ctrl.get_departments()
    assert isinstance(depts, list)
    assert any(d['code'] == 'GROC' for d in depts)


def test_get_suppliers(test_db, supplier_id):
    suppliers = sr_ctrl.get_suppliers()
    assert isinstance(suppliers, list)


def test_update_product_barcode(test_db, product_barcode):
    new_bc = '9300000099880'
    sr_ctrl.update_product_barcode(product_barcode, new_bc)
    import models.product as product_model
    assert product_model.get_by_barcode(new_bc) is not None
