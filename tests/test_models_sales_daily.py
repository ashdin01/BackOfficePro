"""Tests for models/sales_daily.py."""
import pytest
import models.sales_daily as sd_model


@pytest.fixture()
def seeded_sales(db_conn):
    """Insert a handful of sales_daily rows for test assertions."""
    rows = [
        ('2026-05-01', '100', 'Apples', 'FRUIT', 5.0, 10.00),
        ('2026-05-02', '100', 'Apples', 'FRUIT', 3.0,  6.00),
        ('2026-05-01', '200', 'Milk 2L', 'DAIRY', 8.0, 24.00),
    ]
    db_conn.executemany("""
        INSERT OR IGNORE INTO sales_daily
            (sale_date, plu, plu_name, sub_group, quantity, sales_dollars)
        VALUES (?,?,?,?,?,?)
    """, rows)
    db_conn.commit()


class TestTableExists:
    def test_table_exists_returns_true(self, test_db):
        assert sd_model.table_exists() is True


class TestGetGroups:
    def test_empty_when_no_data(self, test_db):
        assert sd_model.get_groups() == []

    def test_returns_distinct_groups(self, test_db, seeded_sales):
        groups = sd_model.get_groups()
        assert 'FRUIT' in groups
        assert 'DAIRY' in groups
        assert len(groups) == len(set(groups))


class TestGetStats:
    def test_zeros_on_empty_range(self, test_db):
        stats = sd_model.get_stats('2026-01-01', '2026-01-31')
        assert stats['total_rev'] == 0
        assert stats['total_qty'] == 0

    def test_totals_correct(self, test_db, seeded_sales):
        stats = sd_model.get_stats('2026-05-01', '2026-05-02')
        assert stats['total_qty'] == pytest.approx(16.0)   # 5+3+8
        assert stats['total_days'] == 2

    def test_group_filter(self, test_db, seeded_sales):
        stats = sd_model.get_stats('2026-05-01', '2026-05-02', group='DAIRY')
        assert stats['total_qty'] == pytest.approx(8.0)

    def test_top_name_populated(self, test_db, seeded_sales):
        stats = sd_model.get_stats('2026-05-01', '2026-05-02')
        assert stats['top_name'] is not None


class TestGetByProduct:
    def test_empty_when_no_data(self, test_db):
        assert sd_model.get_by_product('2026-01-01', '2026-01-31') == []

    def test_groups_by_plu(self, test_db, seeded_sales):
        rows = sd_model.get_by_product('2026-05-01', '2026-05-02')
        plus = {r['plu'] for r in rows}
        assert '100' in plus
        assert '200' in plus

    def test_aggregates_across_dates(self, test_db, seeded_sales):
        rows = sd_model.get_by_product('2026-05-01', '2026-05-02')
        apples = next(r for r in rows if r['plu'] == '100')
        assert apples['qty'] == pytest.approx(8.0)   # 5+3


class TestGetByDay:
    def test_empty_when_no_data(self, test_db):
        assert sd_model.get_by_day('2026-01-01', '2026-01-31') == []

    def test_one_row_per_date(self, test_db, seeded_sales):
        rows = sd_model.get_by_day('2026-05-01', '2026-05-02')
        dates = {r['sale_date'] for r in rows}
        assert dates == {'2026-05-01', '2026-05-02'}


class TestGetLastImportDate:
    def test_returns_none_when_empty(self, test_db):
        assert sd_model.get_last_import_date() is None

    def test_returns_most_recent_date(self, test_db, seeded_sales):
        from datetime import date
        result = sd_model.get_last_import_date()
        assert result == date(2026, 5, 2)


class TestGetSalesForBarcode:
    def test_returns_none_when_no_plu_mapping(self, test_db, product_barcode):
        assert sd_model.get_sales_for_barcode(product_barcode) is None

    def test_returns_dict_when_mapped(self, test_db, db_conn, product_barcode, seeded_sales):
        db_conn.execute(
            "INSERT OR IGNORE INTO plu_barcode_map (plu, barcode) VALUES (100, ?)",
            (product_barcode,)
        )
        db_conn.commit()
        result = sd_model.get_sales_for_barcode(product_barcode)
        assert result is not None
        for key in ('last_week', 'two_weeks', 'this_month', 'ytd'):
            assert key in result
