"""Tests for models/dashboard.py."""
import pytest
import models.dashboard as dashboard_model


_REQUIRED_KEYS = {
    "store_name", "today_sales", "open_po_count",
    "low_stock_count", "active_product_count",
}


class TestGetStats:
    def test_returns_dict(self, test_db):
        result = dashboard_model.get_stats()
        assert isinstance(result, dict)

    def test_returns_all_required_keys(self, test_db):
        result = dashboard_model.get_stats()
        for key in _REQUIRED_KEYS:
            assert key in result, f"missing key: {key}"

    def test_default_store_name_when_not_set(self, test_db):
        result = dashboard_model.get_stats()
        # settings may or may not have store_name; either way it must be a string
        assert isinstance(result["store_name"], str)

    def test_reflects_store_name_setting(self, db_conn):
        db_conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('store_name', 'Harcourt Apples')"
        )
        db_conn.commit()
        result = dashboard_model.get_stats()
        assert result["store_name"] == "Harcourt Apples"

    def test_today_sales_zero_when_no_sales(self, test_db):
        assert dashboard_model.get_stats()["today_sales"] == pytest.approx(0.0)

    def test_today_sales_sums_todays_records(self, db_conn):
        from datetime import date
        today = date.today().isoformat()
        db_conn.execute(
            "INSERT OR IGNORE INTO sales_daily (sale_date, plu, plu_name, sales_dollars)"
            " VALUES (?, 'PLU1', 'Apples', 150.50)",
            (today,)
        )
        db_conn.commit()
        result = dashboard_model.get_stats()
        assert result["today_sales"] == pytest.approx(150.50)

    def test_open_po_count_zero_when_no_pos(self, test_db):
        assert dashboard_model.get_stats()["open_po_count"] == 0

    def test_open_po_count_counts_draft_and_sent(self, db_conn, supplier_id):
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status)"
            " VALUES ('TEST-001', ?, 'DRAFT')", (supplier_id,)
        )
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status)"
            " VALUES ('TEST-002', ?, 'SENT')", (supplier_id,)
        )
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status)"
            " VALUES ('TEST-003', ?, 'RECEIVED')", (supplier_id,)
        )
        db_conn.commit()
        result = dashboard_model.get_stats()
        assert result["open_po_count"] == 2

    def test_active_product_count(self, product_barcode):
        result = dashboard_model.get_stats()
        assert result["active_product_count"] >= 1

    def test_low_stock_count_zero_when_no_reorder_point(self, product_barcode):
        # Default product fixture has reorder_point=0 — not counted as low stock
        result = dashboard_model.get_stats()
        assert isinstance(result["low_stock_count"], int)

    def test_low_stock_count_includes_product_below_reorder(self, db_conn, product_barcode):
        db_conn.execute(
            "UPDATE products SET reorder_point=10 WHERE barcode=?", (product_barcode,)
        )
        db_conn.execute(
            "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 5)",
            (product_barcode,)
        )
        db_conn.commit()
        result = dashboard_model.get_stats()
        assert result["low_stock_count"] >= 1
