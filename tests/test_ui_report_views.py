"""
Smoke tests for report view widgets.

Catches import-time NameError bugs (missing NumItem etc.) and verifies
that each report widget constructs and loads without raising.

Requires pytest-qt and a live display (DISPLAY env var or Xvfb).
"""
from datetime import date
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


# ── GPReport ──────────────────────────────────────────────────────────────────

class TestGPReport:
    def test_import_no_nameerror(self):
        """Importing gp_report must not raise NameError (NumItem was missing)."""
        import views.reports.gp_report  # noqa: F401

    def test_constructs_without_crash(self, qtbot, test_db):
        from views.reports.gp_report import GPReport
        w = GPReport()
        qtbot.addWidget(w)
        assert w is not None

    def test_detail_table_has_expected_columns(self, qtbot, test_db):
        from views.reports.gp_report import GPReport
        w = GPReport()
        qtbot.addWidget(w)
        assert w.detail_table.columnCount() >= 5

    def test_summary_table_exists(self, qtbot, test_db):
        from views.reports.gp_report import GPReport
        w = GPReport()
        qtbot.addWidget(w)
        assert w.summary_table.columnCount() >= 2

    def test_load_empty_db_no_crash(self, qtbot, test_db):
        from views.reports.gp_report import GPReport
        w = GPReport()
        qtbot.addWidget(w)
        w._load()
        assert w.detail_table.rowCount() == 0

    def test_load_with_product_populates_row(self, qtbot, test_db, db_conn, dept_id):
        """A product with cost and sell price appears in the GP detail table."""
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit) "
            "VALUES ('9300000000001', 'Test Biscuits', ?, 3.50, 2.00, 10.0, 12, 1, 'EA')",
            (dept_id,)
        )
        db_conn.commit()
        from views.reports.gp_report import GPReport
        w = GPReport()
        qtbot.addWidget(w)
        assert w.detail_table.rowCount() >= 1

    def test_department_filter_combo_populated(self, qtbot, test_db):
        from views.reports.gp_report import GPReport
        w = GPReport()
        qtbot.addWidget(w)
        assert w.dept_filter.count() >= 1  # at least "All Departments"

    def test_gp_column_contains_percentage(self, qtbot, test_db, db_conn, dept_id):
        """GP% cell must contain a percentage string — proves NumItem is used."""
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit) "
            "VALUES ('9300000000002', 'GP Test', ?, 5.00, 3.00, 10.0, 6, 1, 'EA')",
            (dept_id,)
        )
        db_conn.commit()
        from views.reports.gp_report import GPReport
        from views.widgets.table_items import NumItem
        w = GPReport()
        qtbot.addWidget(w)
        if w.detail_table.rowCount() > 0:
            gp_col = w.detail_table.columnCount() - 1
            cell = w.detail_table.item(0, gp_col)
            assert cell is not None
            assert '%' in cell.text()
            assert isinstance(cell, NumItem)


# ── ReorderReport ─────────────────────────────────────────────────────────────

class TestReorderReport:
    def test_import_no_nameerror(self):
        """Importing reorder_report must not raise NameError (NumItem was missing)."""
        import views.reports.reorder_report  # noqa: F401

    def test_constructs_without_crash(self, qtbot, test_db):
        from views.reports.reorder_report import ReorderReport
        w = ReorderReport()
        qtbot.addWidget(w)
        assert w is not None

    def test_table_has_expected_columns(self, qtbot, test_db):
        from views.reports.reorder_report import ReorderReport
        w = ReorderReport()
        qtbot.addWidget(w)
        assert w.table.columnCount() >= 4

    def test_load_empty_db_no_crash(self, qtbot, test_db):
        from views.reports.reorder_report import ReorderReport
        w = ReorderReport()
        qtbot.addWidget(w)
        w.load()
        assert w.table.rowCount() == 0

    def test_product_above_reorder_point_not_shown(self, qtbot, test_db, db_conn, dept_id):
        """Product with SOH above reorder_point must not appear."""
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit, "
            "reorder_point, reorder_qty) "
            "VALUES ('8000000000001', 'Plenty Stock', ?, 2.00, 1.00, 10.0, 1, 1, 'EA', 5, 20)",
            (dept_id,)
        )
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES ('8000000000001', 50)"
        )
        db_conn.commit()
        from views.reports.reorder_report import ReorderReport
        w = ReorderReport()
        qtbot.addWidget(w)
        descriptions = [
            w.table.item(r, 1).text() if w.table.item(r, 1) else ''
            for r in range(w.table.rowCount())
        ]
        assert 'Plenty Stock' not in descriptions

    def test_product_below_reorder_point_shown(self, qtbot, test_db, db_conn, dept_id):
        """Product with SOH below reorder_point must appear in the table."""
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit, "
            "reorder_point, reorder_qty) "
            "VALUES ('8000000000002', 'Low Stock Item', ?, 2.00, 1.00, 10.0, 1, 1, 'EA', 10, 30)",
            (dept_id,)
        )
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES ('8000000000002', 2)"
        )
        db_conn.commit()
        from views.reports.reorder_report import ReorderReport
        w = ReorderReport()
        qtbot.addWidget(w)
        descriptions = [
            w.table.item(r, 1).text() if w.table.item(r, 1) else ''
            for r in range(w.table.rowCount())
        ]
        assert 'Low Stock Item' in descriptions

    def test_quantity_cell_is_numitem(self, qtbot, test_db, db_conn, dept_id):
        """SOH cell must be a NumItem — proves NumItem was imported correctly."""
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit, "
            "reorder_point, reorder_qty) "
            "VALUES ('8000000000003', 'NumItem Check', ?, 2.00, 1.00, 10.0, 1, 1, 'EA', 10, 20)",
            (dept_id,)
        )
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES ('8000000000003', 0)"
        )
        db_conn.commit()
        from views.reports.reorder_report import ReorderReport
        from views.widgets.table_items import NumItem
        w = ReorderReport()
        qtbot.addWidget(w)
        if w.table.rowCount() > 0:
            item = w.table.item(0, 4)  # on_hand / quantity column (col 4)
            assert item is not None
            assert isinstance(item, NumItem)


class TestWeightVarianceReport:
    def test_import_no_nameerror(self):
        import views.reports.weight_variance_report  # noqa: F401

    def test_constructs_without_crash(self, qtbot, test_db):
        from views.reports.weight_variance_report import WeightVarianceReport
        w = WeightVarianceReport()
        qtbot.addWidget(w)
        assert w is not None

    def test_table_has_expected_columns(self, qtbot, test_db):
        from views.reports.weight_variance_report import WeightVarianceReport
        w = WeightVarianceReport()
        qtbot.addWidget(w)
        assert w.table.columnCount() == 7

    def test_load_empty_db_no_crash(self, qtbot, test_db):
        from views.reports.weight_variance_report import WeightVarianceReport
        w = WeightVarianceReport()
        qtbot.addWidget(w)
        w.load()
        assert w.table.rowCount() == 0

    def test_variable_weight_product_shown_with_received_and_sold(
        self, qtbot, test_db, db_conn, dept_id, supplier_id
    ):
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, supplier_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit, variable_weight) "
            "VALUES ('8000000000010', 'Weighed Item', ?, ?, 15.00, 8.00, 10.0, 1, 1, 'KG', 1)",
            (dept_id, supplier_id)
        )
        db_conn.execute(
            "INSERT OR IGNORE INTO plu_barcode_map (plu, barcode) VALUES (910, '8000000000010')"
        )
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type, received_at)
            VALUES ('PO-WVUI-1', ?, 'RECEIVED', 'PO', ?)
        """, (supplier_id, f"{date.today().isoformat()} 10:00:00"))
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='PO-WVUI-1'"
        ).fetchone()["id"]
        db_conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty,
                                   received_weight, pack_qty, unit_cost)
            VALUES (?, '8000000000010', 'Test Line', 1, 1, 10.0, 1, 5.0)
        """, (po_id,))
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, weight_kg, quantity, sales_dollars)
            VALUES (?, '910', 'Weighed Item', 6.0, 1, 0)
        """, (date.today().isoformat(),))
        db_conn.commit()

        from views.reports.weight_variance_report import WeightVarianceReport
        w = WeightVarianceReport()
        qtbot.addWidget(w)
        w.load()

        descriptions = [
            w.table.item(r, 1).text() if w.table.item(r, 1) else ''
            for r in range(w.table.rowCount())
        ]
        assert 'Weighed Item' in descriptions
        row = descriptions.index('Weighed Item')
        assert w.table.item(row, 3).text() == "10.00"
        assert w.table.item(row, 4).text() == "6.00"
        assert w.table.item(row, 5).text() == "4.00"
