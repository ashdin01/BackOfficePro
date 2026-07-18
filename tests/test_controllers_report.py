"""Tests for controllers/report_controller.py."""
import pytest
import controllers.report_controller as report_ctrl


# ── Smoke tests: every function returns the right container type ───────────────

class TestReturnTypes:
    def test_get_stock_valuation_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_stock_valuation(), list)

    def test_get_below_reorder_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_below_reorder(), list)

    def test_get_all_products_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_all_products(), list)

    def test_get_all_suppliers_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_all_suppliers(), list)

    def test_get_all_departments_returns_list(self, test_db):
        result = report_ctrl.get_all_departments()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_get_setting_returns_str(self, test_db):
        assert isinstance(report_ctrl.get_setting("store_name", "default"), str)

    def test_get_stock_valuation_summary_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_stock_valuation_summary(), list)

    def test_get_stock_valuation_detail_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_stock_valuation_detail(), list)

    def test_get_reorder_items_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_reorder_items(), list)

    def test_get_stock_movements_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_stock_movements(), list)

    def test_get_gst_report_returns_dict_with_keys(self, test_db):
        result = report_ctrl.get_gst_report("2026-01-01", "2026-12-31")
        assert isinstance(result, dict)
        assert "sales" in result
        assert "purchases" in result

    def test_get_gp_data_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_gp_data(), list)

    def test_get_gp_summary_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_gp_summary(), list)

    def test_get_liquor_tracking_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_liquor_tracking(), list)

    def test_get_supplier_sales_returns_tuple(self, test_db):
        rows, totals = report_ctrl.get_supplier_sales()
        assert isinstance(rows, list)
        assert isinstance(totals, list)

    def test_get_writeoff_data_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_writeoff_data("2026-01-01", "2026-12-31"), list)

    def test_get_combined_daily_revenue_returns_dict(self, test_db):
        assert isinstance(report_ctrl.get_combined_daily_revenue("2026-01-01", "2026-12-31"), dict)

    def test_get_weight_variance_returns_list(self, test_db):
        assert isinstance(report_ctrl.get_weight_variance("2026-01-01", "2026-12-31"), list)


# ── Functional tests with data ─────────────────────────────────────────────────

class TestWithData:
    def test_get_all_products_includes_inserted_product(self, test_db, product_barcode):
        result = report_ctrl.get_all_products(active_only=True)
        barcodes = [r["barcode"] for r in result]
        assert product_barcode in barcodes

    def test_get_all_products_inactive_excluded_by_default(self, test_db, db_conn, dept_id, supplier_id):
        db_conn.execute("""
            INSERT INTO products (barcode, description, department_id, supplier_id,
                sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
            VALUES ('INACTIVE001', 'Inactive Product', ?, ?, 1.0, 0.5, 10.0, 1, 'EA', 0, 'EA')
        """, (dept_id, supplier_id))
        db_conn.commit()
        result = report_ctrl.get_all_products(active_only=True)
        barcodes = [r["barcode"] for r in result]
        assert "INACTIVE001" not in barcodes

    def test_get_all_products_inactive_included_when_requested(self, test_db, db_conn, dept_id, supplier_id):
        db_conn.execute("""
            INSERT INTO products (barcode, description, department_id, supplier_id,
                sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
            VALUES ('INACTIVE002', 'Inactive Product 2', ?, ?, 1.0, 0.5, 10.0, 1, 'EA', 0, 'EA')
        """, (dept_id, supplier_id))
        db_conn.commit()
        result = report_ctrl.get_all_products(active_only=False)
        barcodes = [r["barcode"] for r in result]
        assert "INACTIVE002" in barcodes

    def test_get_setting_returns_default_when_missing(self, test_db):
        result = report_ctrl.get_setting("nonexistent_key_xyz", "fallback")
        assert result == "fallback"

    def test_get_below_reorder_shows_low_stock_product(self, test_db, db_conn, product_barcode):
        # Set reorder_point above current SOH (SOH=0 by default, reorder_point=5)
        db_conn.execute(
            "UPDATE products SET reorder_point=5 WHERE barcode=?", (product_barcode,)
        )
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, 2)"
            " ON CONFLICT(barcode) DO UPDATE SET quantity=2",
            (product_barcode,),
        )
        db_conn.commit()
        result = report_ctrl.get_below_reorder()
        barcodes = [r["barcode"] for r in result]
        assert product_barcode in barcodes

    def test_get_stock_movements_filtered_by_barcode(self, test_db, db_conn, product_barcode):
        db_conn.execute("""
            INSERT INTO stock_movements (barcode, movement_type, quantity, reference, created_by, source)
            VALUES (?, 'RECEIVE', 10, 'REF-001', 'test', 'TEST')
        """, (product_barcode,))
        db_conn.commit()
        result = report_ctrl.get_stock_movements(barcode=product_barcode)
        assert len(result) >= 1
        assert all(r["barcode"] == product_barcode for r in result)

    def test_get_combined_daily_revenue_empty_range(self, test_db):
        result = report_ctrl.get_combined_daily_revenue("2026-01-01", "2026-01-03")
        assert isinstance(result, dict)

    def test_get_supplier_sales_totals_length(self, test_db):
        _, totals = report_ctrl.get_supplier_sales()
        assert len(totals) == 8
