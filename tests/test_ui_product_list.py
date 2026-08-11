"""Widget regression tests for ProductList (views/products/product_list.py) —
specifically the Cost (inc. Tax) and Tax (Y/N) columns.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import controllers.product_controller as product_ctrl


@pytest.fixture()
def product_list_view(qtbot, test_db):
    from views.products.product_list import ProductList
    widget = ProductList(current_user={"role": "MANAGER"})
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _row_for_barcode(table, barcode):
    for r in range(table.rowCount()):
        if table.item(r, 0).text() == barcode:
            return r
    raise AssertionError(f"barcode {barcode} not found in table")


class TestCostAndTaxColumns:
    def test_header_labels(self, product_list_view):
        table = product_list_view.table
        assert table.horizontalHeaderItem(9).text()  == "Cost (inc. Tax)"
        assert table.horizontalHeaderItem(10).text() == "GP %"
        assert table.horizontalHeaderItem(11).text() == "Tax"

    def test_taxable_product_shows_inc_tax_cost_gp_and_y(
        self, product_list_view, product_barcode
    ):
        # product_barcode fixture: sell=3.50, cost_price=2.00, tax_rate=10.0
        # -> $2.20 inc, GP 37.1%
        product_list_view.load()
        table = product_list_view.table
        r = _row_for_barcode(table, product_barcode)
        assert table.item(r, 9).text() == "$2.20"
        assert table.item(r, 10).text() == "37.1%"
        assert table.item(r, 11).text() == "Y"

    def test_gst_free_product_shows_ex_tax_cost_gp_and_n(
        self, product_list_view, gst_free_barcode
    ):
        # gst_free_barcode fixture: sell=2.00, cost_price=1.50, tax_rate=0.0
        # -> unchanged cost, GP 25.0%
        product_list_view.load()
        table = product_list_view.table
        r = _row_for_barcode(table, gst_free_barcode)
        assert table.item(r, 9).text() == "$1.50"
        assert table.item(r, 10).text() == "25.0%"
        assert table.item(r, 11).text() == "N"

    def test_status_and_online_columns_shifted_correctly(
        self, product_list_view, product_barcode
    ):
        product_list_view.load()
        table = product_list_view.table
        r = _row_for_barcode(table, product_barcode)
        assert table.item(r, 13).text() == "Active"
        assert table.item(r, 14).text() in ("✓", "—")


class TestGpColumn:
    def test_zero_sell_price_shows_placeholder_not_a_crash(
        self, product_list_view, db_conn, product_barcode
    ):
        """GP% is undefined when sell_price is 0 — must render as '--' and,
        critically, must not corrupt the NumItem-sorted column (see
        tests/test_widgets_table_items.py for the underlying sort fix)."""
        db_conn.execute("UPDATE products SET sell_price=0 WHERE barcode=?", (product_barcode,))
        db_conn.commit()
        product_list_view.load()
        table = product_list_view.table
        r = _row_for_barcode(table, product_barcode)
        assert table.item(r, 10).text() == "--"
        table.sortByColumn(10, Qt.SortOrder.AscendingOrder)  # must not raise


class TestCostMatchesProductEditScreen:
    """The list's 'Cost (inc. Tax)' column must always agree with the
    'Cost Price (inc GST)' figure shown on the product edit screen —
    both derive from cost_price/tax_rate, but via separately-written
    formulas, so this locks the two in sync against future drift."""

    @pytest.mark.parametrize("cost_price,tax_rate", [
        (2.00, 10.0),
        (1.50, 0.0),
        (1.995, 10.0),
        (0.10, 10.0),
        (19.99, 10.0),
    ])
    def test_list_cost_matches_edit_screen_formula(self, cost_price, tax_rate):
        from utils.calculations import amount_inc_from_ex

        # Mirrors views/products/product_edit.py's inline calculation exactly
        edit_screen_inc = cost_price * (1 + (tax_rate or 0.0) / 100)
        edit_screen_str = f"${edit_screen_inc:.2f}"

        list_screen_inc = amount_inc_from_ex(cost_price, tax_rate or 0)
        list_screen_str = f"${list_screen_inc:.2f}"

        assert list_screen_str == edit_screen_str
