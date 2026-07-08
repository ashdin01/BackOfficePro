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
        filtered = report_model.get_stock_valuation_summary(dept_ids=[dept_id])
        assert len(filtered) <= len(all_rows)

    def test_empty_dept_ids_returns_nothing(self, stocked_product):
        assert report_model.get_stock_valuation_summary(dept_ids=[]) == []


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
        filtered = report_model.get_stock_valuation_detail(dept_ids=[dept_id])
        for r in filtered:
            assert r["dept_name"] is not None

    def test_empty_dept_ids_returns_nothing(self, stocked_product):
        assert report_model.get_stock_valuation_detail(dept_ids=[]) == []

    def test_as_of_date_reconstructs_historical_quantity(self, db_conn, stocked_product):
        """50 units on hand today; a +20 movement was recorded today, so
        as-of-yesterday should reverse it back to 30."""
        db_conn.execute(
            "INSERT INTO stock_movements (barcode, movement_type, quantity, created_at) "
            "VALUES (?, 'ADJUSTMENT_IN', 20, datetime('now'))",
            (stocked_product,)
        )
        db_conn.commit()

        yesterday = "2020-01-01"  # any date before the movement above
        rows = report_model.get_stock_valuation_detail(as_of_date=yesterday)
        row = next(r for r in rows if r["barcode"] == stocked_product)
        assert row["quantity"] == 30

        rows_today = report_model.get_stock_valuation_detail()
        row_today = next(r for r in rows_today if r["barcode"] == stocked_product)
        assert row_today["quantity"] == 50


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

    def test_gst_free_sales_counted_in_exempt(self, test_db, db_conn, product_barcode):
        # GST-free product (tax_rate=0) — sales counted as exempt
        db_conn.execute("UPDATE products SET tax_rate=0 WHERE barcode=?", (product_barcode,))
        db_conn.execute(
            "INSERT OR IGNORE INTO plu_barcode_map (plu, barcode) VALUES (400, ?)",
            (product_barcode,)
        )
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
            VALUES ('2026-05-01', '400', 'GST Free Item', 2, 10.00)
        """)
        db_conn.commit()
        result = report_model.get_gst_report("2026-05-01", "2026-05-01")
        assert result["sales"]["exempt_sales"] == pytest.approx(10.00)

    def test_taxable_sale_counted_and_gst_calculated(self, test_db, db_conn, product_barcode):
        # product_barcode fixture has tax_rate=10.0
        db_conn.execute(
            "INSERT OR IGNORE INTO plu_barcode_map (plu, barcode) VALUES (500, ?)",
            (product_barcode,)
        )
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
            VALUES ('2026-05-01', '500', 'Taxable Item', 2, 11.00)
        """)
        db_conn.commit()
        result = report_model.get_gst_report("2026-05-01", "2026-05-01")
        assert result["sales"]["taxable_sales"] == pytest.approx(11.00)
        assert result["sales"]["gst_collected"] == pytest.approx(1.00)


class TestGstPaid:
    def _make_received_po(self, db_conn, supplier_id, barcode, received_qty=10, pack_qty=1,
                          unit_cost=5.0, actual_cost=0, received_weight=0):
        po_number = f"PO-GST-{barcode}"
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type, received_at)
            VALUES (?, ?, 'RECEIVED', 'PO', '2026-05-01 10:00:00')
        """, (po_number, supplier_id))
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number=?", (po_number,)
        ).fetchone()["id"]
        db_conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty,
                                   received_weight, pack_qty, unit_cost, actual_cost)
            VALUES (?, ?, 'Test Line', ?, ?, ?, ?, ?, ?)
        """, (po_id, barcode, received_qty, received_qty, received_weight,
              pack_qty, unit_cost, actual_cost))
        db_conn.commit()
        return po_id

    def test_taxable_purchase_counted(self, test_db, db_conn, supplier_id, product_barcode):
        # product_barcode fixture has tax_rate=10.0
        self._make_received_po(db_conn, supplier_id, product_barcode,
                               received_qty=10, pack_qty=1, unit_cost=1.10)
        result = report_model.get_gst_report("2026-05-01", "2026-05-01")
        assert result["purchases"]["taxable_purchases"] == pytest.approx(11.00)
        assert result["purchases"]["gst_paid"] == pytest.approx(1.00)

    def test_exempt_purchase_counted(self, test_db, db_conn, supplier_id, gst_free_barcode):
        self._make_received_po(db_conn, supplier_id, gst_free_barcode,
                               received_qty=5, pack_qty=1, unit_cost=2.00)
        result = report_model.get_gst_report("2026-05-01", "2026-05-01")
        assert result["purchases"]["exempt_purchases"] == pytest.approx(10.00)

    def test_variable_weight_purchase_uses_weight_times_cost(
        self, test_db, db_conn, supplier_id, product_barcode
    ):
        db_conn.execute("UPDATE products SET variable_weight=1 WHERE barcode=?", (product_barcode,))
        db_conn.commit()
        self._make_received_po(db_conn, supplier_id, product_barcode, received_qty=1, pack_qty=1,
                               unit_cost=5.00, received_weight=3.0)
        result = report_model.get_gst_report("2026-05-01", "2026-05-01")
        # line_total = weight(3.0) * unit_cost(5.00) = 15.00, taxable at 10%
        assert result["purchases"]["taxable_purchases"] == pytest.approx(15.00)


class TestGetStockMovementsDateFilters:
    def test_filter_by_date_from(self, test_db, db_conn, product_barcode):
        db_conn.execute("""
            INSERT INTO stock_movements (barcode, movement_type, quantity, reference,
                                         created_by, source, created_at)
            VALUES (?, 'RECEIPT', 5, 'PO-DATE', 'test', 'UI', '2026-04-01 10:00:00')
        """, (product_barcode,))
        db_conn.commit()
        rows = report_model.get_stock_movements(date_from="2026-05-01")
        assert not any(r["reference"] == "PO-DATE" for r in rows)

    def test_filter_by_date_to(self, test_db, db_conn, product_barcode):
        db_conn.execute("""
            INSERT INTO stock_movements (barcode, movement_type, quantity, reference,
                                         created_by, source, created_at)
            VALUES (?, 'RECEIPT', 5, 'PO-FUTURE', 'test', 'UI', '2026-12-01 10:00:00')
        """, (product_barcode,))
        db_conn.commit()
        rows = report_model.get_stock_movements(date_to="2026-01-01")
        assert not any(r["reference"] == "PO-FUTURE" for r in rows)


class TestGetGpData:
    def test_returns_list(self, test_db, product_barcode):
        rows = report_model.get_gp_data()
        assert isinstance(rows, list)

    def test_dept_filter_reduces_results(self, test_db, product_barcode, dept_id):
        all_rows = report_model.get_gp_data()
        filtered  = report_model.get_gp_data(dept_id=dept_id)
        assert len(filtered) <= len(all_rows)

    def test_healthy_filter(self, test_db, product_barcode):
        rows = report_model.get_gp_data(gp_filter="healthy")
        assert isinstance(rows, list)

    def test_marginal_filter(self, test_db, product_barcode):
        rows = report_model.get_gp_data(gp_filter="marginal")
        assert isinstance(rows, list)

    def test_low_filter(self, test_db, product_barcode):
        rows = report_model.get_gp_data(gp_filter="low")
        assert isinstance(rows, list)


class TestGetGpSummary:
    def test_returns_list(self, test_db):
        assert isinstance(report_model.get_gp_summary(), list)

    def test_dept_filter(self, test_db, dept_id):
        rows = report_model.get_gp_summary(dept_id=dept_id)
        assert isinstance(rows, list)


class TestGetLiquorTracking:
    def test_returns_list(self, test_db):
        rows = report_model.get_liquor_tracking(date_from="2026-01-01", date_to="2026-12-31")
        assert isinstance(rows, list)

    def test_dept_filter(self, test_db, dept_id):
        rows = report_model.get_liquor_tracking(
            dept_id=dept_id, date_from="2026-01-01", date_to="2026-12-31"
        )
        assert isinstance(rows, list)


class TestGetSupplierSales:
    def test_returns_rows_and_totals(self, test_db):
        rows, totals = report_model.get_supplier_sales()
        assert isinstance(rows, list)
        assert isinstance(totals, list)
        assert len(totals) == 8

    def test_supplier_filter(self, test_db, supplier_id):
        rows, totals = report_model.get_supplier_sales(supplier_id=supplier_id)
        assert isinstance(rows, list)

    def test_with_sales_data_aggregated_in_sql(
        self, test_db, db_conn, supplier_id, product_barcode
    ):
        db_conn.execute(
            "INSERT OR IGNORE INTO plu_barcode_map (plu, barcode) VALUES (501, ?)",
            (product_barcode,)
        )
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
            VALUES ('2000-01-15', '501', 'Test Product', 7, 24.50)
        """)
        db_conn.commit()
        rows, totals = report_model.get_supplier_sales(supplier_id=supplier_id)
        assert isinstance(rows, list)
        row = next((r for r in rows if r['barcode'] == product_barcode), None)
        assert row is not None
        assert len(row['qty']) == 8
        # w7 is 'all time' (2000-01-01 to today), must include our 7-unit sale
        assert row['qty'][7] == 7
        assert totals[7] >= 7


class TestGetWriteoffData:
    def test_returns_list(self, test_db):
        rows = report_model.get_writeoff_data("2026-01-01", "2026-12-31")
        assert isinstance(rows, list)

    def test_dept_filter(self, test_db, dept_id):
        rows = report_model.get_writeoff_data("2026-01-01", "2026-12-31", dept_id=dept_id)
        assert isinstance(rows, list)

    def test_spoilage_category_filter(self, test_db):
        rows = report_model.get_writeoff_data("2026-01-01", "2026-12-31", category="Spoilage")
        assert isinstance(rows, list)

    def test_shrinkage_category_filter(self, test_db):
        rows = report_model.get_writeoff_data("2026-01-01", "2026-12-31", category="Shrinkage")
        assert isinstance(rows, list)

    def test_admin_category_filter(self, test_db):
        rows = report_model.get_writeoff_data("2026-01-01", "2026-12-31", category="Admin")
        assert isinstance(rows, list)


class TestGetCombinedDailyRevenue:
    def test_returns_dict(self, test_db):
        result = report_model.get_combined_daily_revenue("2026-05-01", "2026-05-31")
        assert isinstance(result, dict)

    def test_pos_sales_appear(self, test_db, db_conn):
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
            VALUES ('2026-05-10', '999', 'Product', 1, 5.00)
        """)
        db_conn.commit()
        result = report_model.get_combined_daily_revenue("2026-05-01", "2026-05-31")
        assert "2026-05-10" in result
        assert result["2026-05-10"]["pos"] == pytest.approx(5.00)

    def test_ar_sales_appear(self, test_db, customer_id, db_conn):
        db_conn.execute("""
            INSERT INTO ar_invoices
                (invoice_number, customer_id, invoice_date, due_date, status,
                 subtotal, gst_amount, total)
            VALUES ('INV-REV01', ?, '2026-05-12', '2026-06-30', 'SENT',
                    100.0, 10.0, 110.0)
        """, (customer_id,))
        db_conn.commit()
        result = report_model.get_combined_daily_revenue("2026-05-01", "2026-05-31")
        assert "2026-05-12" in result
        assert result["2026-05-12"]["ar"] == pytest.approx(110.0)


class TestGetReorderItemsFilters:
    def test_returns_list(self, test_db):
        rows = report_model.get_reorder_items()
        assert isinstance(rows, list)

    def test_dept_filter(self, test_db, dept_id):
        rows = report_model.get_reorder_items(dept_id=dept_id)
        assert isinstance(rows, list)

    def test_supplier_filter(self, test_db, supplier_id):
        rows = report_model.get_reorder_items(supplier_id=supplier_id)
        assert isinstance(rows, list)
