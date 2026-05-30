"""Tests for models/report.py — key query functions."""
import pytest
import models.report as report_model


@pytest.fixture()
def stocked_product(db_conn, product_barcode):
    """Give the standard test product 50 units of stock."""
    db_conn.execute(
        "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 50)",
        (product_barcode,)
    )
    db_conn.commit()
    return product_barcode


@pytest.fixture()
def low_stock_product(db_conn, product_barcode):
    """Set reorder_point=20 with only 5 units on hand — triggers low-stock report."""
    db_conn.execute(
        "UPDATE products SET reorder_point=20 WHERE barcode=?", (product_barcode,)
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 5)",
        (product_barcode,)
    )
    db_conn.commit()
    return product_barcode


class TestGetStockValuationSummary:
    def test_returns_list(self, test_db):
        assert isinstance(report_model.get_stock_valuation_summary(), list)

    def test_includes_product_with_stock(self, stocked_product):
        rows = report_model.get_stock_valuation_summary()
        assert len(rows) >= 1

    def test_has_required_columns(self, stocked_product):
        rows = report_model.get_stock_valuation_summary()
        row = rows[0]
        for col in ("dept_name", "product_count", "total_units", "cost_value", "sell_value"):
            assert col in row.keys(), f"missing column: {col}"

    def test_dept_filter(self, stocked_product, dept_id):
        all_rows = report_model.get_stock_valuation_summary()
        filtered = report_model.get_stock_valuation_summary(dept_id=dept_id)
        assert len(filtered) <= len(all_rows)


class TestGetStockValuationDetail:
    def test_returns_list(self, test_db):
        assert isinstance(report_model.get_stock_valuation_detail(), list)

    def test_includes_stocked_product(self, stocked_product):
        rows = report_model.get_stock_valuation_detail()
        barcodes = [r["barcode"] for r in rows]
        assert stocked_product in barcodes

    def test_has_required_columns(self, stocked_product):
        rows = report_model.get_stock_valuation_detail()
        row = next(r for r in rows if r["barcode"] == stocked_product)
        for col in ("barcode", "description", "cost_price", "sell_price",
                    "quantity", "cost_value", "sell_value"):
            assert col in row.keys()

    def test_quantity_reflects_stock_on_hand(self, stocked_product):
        rows = report_model.get_stock_valuation_detail()
        row = next(r for r in rows if r["barcode"] == stocked_product)
        assert row["quantity"] == 50

    def test_dept_filter_restricts_results(self, stocked_product, dept_id):
        filtered = report_model.get_stock_valuation_detail(dept_id=dept_id)
        for r in filtered:
            assert r["dept_name"] is not None


class TestGetReorderItems:
    def test_returns_list(self, test_db):
        assert isinstance(report_model.get_reorder_items(), list)

    def test_includes_low_stock_product(self, low_stock_product):
        rows = report_model.get_reorder_items()
        barcodes = [r["barcode"] for r in rows]
        assert low_stock_product in barcodes

    def test_excludes_product_above_reorder_point(self, stocked_product):
        rows = report_model.get_reorder_items()
        barcodes = [r["barcode"] for r in rows]
        assert stocked_product not in barcodes

    def test_supplier_filter(self, low_stock_product, supplier_id):
        all_rows = report_model.get_reorder_items()
        filtered = report_model.get_reorder_items(supplier_id=supplier_id)
        assert len(filtered) <= len(all_rows)


class TestGetStockMovements:
    def test_returns_list(self, test_db):
        assert isinstance(report_model.get_stock_movements(), list)

    def test_filter_by_barcode(self, db_conn, product_barcode):
        db_conn.execute("""
            INSERT INTO stock_movements (barcode, movement_type, quantity, reference, created_by, source)
            VALUES (?, 'RECEIPT', 10, 'PO-001', 'test', 'API')
        """, (product_barcode,))
        db_conn.commit()
        rows = report_model.get_stock_movements(barcode=product_barcode)
        assert len(rows) >= 1
        for r in rows:
            assert r["barcode"] == product_barcode

    def test_filter_by_move_type(self, db_conn, product_barcode):
        db_conn.execute("""
            INSERT INTO stock_movements (barcode, movement_type, quantity, reference, created_by, source)
            VALUES (?, 'ADJUST', -5, 'ADJ-001', 'test', 'UI')
        """, (product_barcode,))
        db_conn.commit()
        rows = report_model.get_stock_movements(move_type="ADJUST")
        for r in rows:
            assert r["movement_type"] == "ADJUST"

    def test_limit_respected(self, db_conn, product_barcode):
        for i in range(5):
            db_conn.execute("""
                INSERT INTO stock_movements (barcode, movement_type, quantity, reference, created_by, source)
                VALUES (?, 'RECEIPT', 1, ?, 'test', 'UI')
            """, (product_barcode, f"PO-{i:03d}"))
        db_conn.commit()
        rows = report_model.get_stock_movements(limit=3)
        assert len(rows) <= 3


class TestGetGstReport:
    def test_returns_dict_with_required_keys(self, test_db):
        result = report_model.get_gst_report("2026-01-01", "2026-01-31")
        assert isinstance(result, dict)
        assert "sales" in result
        assert "purchases" in result

    def test_sales_subdict_has_gst_collected(self, test_db):
        result = report_model.get_gst_report("2026-01-01", "2026-01-31")
        assert "gst_collected" in result["sales"]
        assert "taxable_sales" in result["sales"]

    def test_purchases_subdict_has_gst_paid(self, test_db):
        result = report_model.get_gst_report("2026-01-01", "2026-01-31")
        assert "gst_paid" in result["purchases"]
        assert "taxable_purchases" in result["purchases"]

    def test_zero_values_on_empty_db(self, test_db):
        result = report_model.get_gst_report("2020-01-01", "2020-12-31")
        assert result["sales"]["gst_collected"] == pytest.approx(0.0)
        assert result["purchases"]["gst_paid"] == pytest.approx(0.0)
