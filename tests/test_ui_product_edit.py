"""Widget regression tests for ProductEdit (views/products/product_edit.py).

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.product_controller as product_ctrl


@pytest.fixture()
def product_edit_view(qtbot, test_db, product_barcode):
    from views.products.product_edit import ProductEdit
    widget = ProductEdit(product_barcode)
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


# ── Loading ───────────────────────────────────────────────────────────────────

class TestLoad:
    def test_fields_match_product_row(self, product_edit_view, product_barcode):
        product = product_ctrl.get_product_by_barcode(product_barcode)
        assert product_edit_view._description == product['description']
        assert product_edit_view._sell_price == product['sell_price']
        assert product_edit_view._cost_price == product['cost_price']

    def test_not_a_selling_unit_by_default(self, product_edit_view):
        assert product_edit_view._is_selling_unit is False

    def test_read_only_title_shows_marker(self, qtbot, test_db, product_barcode):
        from views.products.product_edit import ProductEdit
        w = ProductEdit(product_barcode, read_only=True)
        qtbot.addWidget(w)
        assert "[Read Only]" in w.windowTitle()

    def test_normal_title_has_no_marker(self, product_edit_view):
        assert "[Read Only]" not in product_edit_view.windowTitle()

    def test_reorder_point_labelled_as_minimum(self, product_edit_view):
        """Standardised to match Add Product's "Reorder Point (Min)" — was
        just "Reorder Point" here, which read inconsistently across the two
        screens for the same field."""
        from PyQt6.QtWidgets import QLabel
        texts = [lbl.text() for lbl in product_edit_view.findChildren(QLabel)]
        assert "Reorder Point (Min)" in texts


# ── _save ─────────────────────────────────────────────────────────────────────

class TestSave:
    def test_changed_values_persist_to_db(self, product_edit_view, product_barcode):
        product_edit_view._description = "Updated Description"
        product_edit_view._sell_price = 12.34

        product_edit_view._save()

        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row['description'] == "Updated Description"
        assert row['sell_price'] == pytest.approx(12.34)

    def test_save_closes_widget(self, product_edit_view):
        product_edit_view.show()
        QApplication.processEvents()
        assert product_edit_view.isVisible()

        product_edit_view._save()
        QApplication.processEvents()

        assert not product_edit_view.isVisible()

    def test_save_calls_on_save_callback(self, qtbot, test_db, product_barcode):
        from views.products.product_edit import ProductEdit
        on_save = MagicMock()
        w = ProductEdit(product_barcode, on_save=on_save)
        qtbot.addWidget(w)

        w._save()

        on_save.assert_called_once()

    def test_read_only_save_is_noop(self, qtbot, test_db, product_barcode):
        from views.products.product_edit import ProductEdit
        w = ProductEdit(product_barcode, read_only=True)
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()
        original = product_ctrl.get_product_by_barcode(product_barcode)['description']
        w._description = "Should Not Be Saved"

        w._save()

        assert product_ctrl.get_product_by_barcode(product_barcode)['description'] == original
        # Read-only save() returns immediately rather than closing the widget.
        assert w.isVisible()

    def test_blank_description_shows_validation_warning_and_stays_open(
        self, product_edit_view
    ):
        product_edit_view._description = "   "
        with patch('views.products.product_edit.QMessageBox') as mock_mb:
            product_edit_view._save()
            mock_mb.warning.assert_called_once()
        assert product_edit_view.isVisible()

    def test_unexpected_error_shows_error_dialog_not_crash(self, product_edit_view, monkeypatch):
        monkeypatch.setattr(
            product_ctrl, "save_product",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db exploded")),
        )
        with patch('views.products.product_edit.show_error') as mock_show_error:
            product_edit_view._save()  # must not raise
            mock_show_error.assert_called_once()
        assert product_edit_view.isVisible()


# ── Edit popups ───────────────────────────────────────────────────────────────

class TestEditDescription:
    def test_updates_internal_state_and_label(self, product_edit_view):
        with patch('views.products.product_edit.text_popup', return_value="New Desc"):
            product_edit_view._edit_description()
        assert product_edit_view._description == "New Desc"
        assert product_edit_view.lbl_desc.text() == "New Desc"

    def test_cancelled_popup_leaves_value_unchanged(self, product_edit_view):
        original = product_edit_view._description
        with patch('views.products.product_edit.text_popup', return_value=None):
            product_edit_view._edit_description()
        assert product_edit_view._description == original


# ── Selling-unit guard ──────────────────────────────────────────────────────────

class TestSellingUnitGuard:
    @pytest.fixture()
    def selling_unit_view(self, qtbot, test_db, dept_id, supplier_id, product_barcode):
        # The guard only triggers when the barcode is *itself* a real product
        # row that also happens to be registered as a selling unit of another
        # product (e.g. a loose item that's also sold as a half-case).
        su_barcode = '9300000099780'
        product_ctrl.add_product(
            su_barcode, 'Also A Real Product', dept_id,
            supplier_id=supplier_id, sell_price=2.00, cost_price=1.00, tax_rate=10.0,
        )
        product_ctrl.add_selling_unit(product_barcode, su_barcode, '7002', 'Half', 0.5, 2.00)
        from views.products.product_edit import ProductEdit
        w = ProductEdit(su_barcode)
        qtbot.addWidget(w)
        return w

    def test_is_selling_unit_true(self, selling_unit_view):
        assert selling_unit_view._is_selling_unit is True

    def test_edit_description_blocked_with_warning(self, selling_unit_view):
        with patch('views.products.product_edit.text_popup') as mock_popup, \
             patch('views.products.product_edit.QMessageBox') as mock_mb:
            selling_unit_view._edit_description()
            mock_popup.assert_not_called()
            mock_mb.information.assert_called_once()
