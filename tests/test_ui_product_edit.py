"""Widget regression tests for ProductEdit (views/products/product_edit.py).

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import os
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

    def test_non_variable_weight_product_has_no_volume_sold_row(self, product_edit_view):
        """Volume Sold only makes sense for weighed items — must not show for
        a normal each-priced product."""
        from PyQt6.QtWidgets import QLabel
        texts = [lbl.text() for lbl in product_edit_view.findChildren(QLabel)]
        assert "Volume Sold (This Month)" not in texts
        assert not hasattr(product_edit_view, "lbl_vol_sold")

    def test_variable_weight_product_shows_volume_sold_row(self, qtbot, test_db, db_conn, dept_id, supplier_id):
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, supplier_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit, variable_weight) "
            "VALUES ('8000000000020', 'Weighed Item', ?, ?, 15.00, 8.00, 10.0, 1, 1, 'KG', 1)",
            (dept_id, supplier_id)
        )
        db_conn.commit()
        from views.products.product_edit import ProductEdit
        from PyQt6.QtWidgets import QLabel
        w = ProductEdit('8000000000020')
        qtbot.addWidget(w)
        texts = [lbl.text() for lbl in w.findChildren(QLabel)]
        assert "Volume Sold (This Month)" in texts
        assert hasattr(w, "lbl_vol_sold")
        assert "0.00 kg" in w.lbl_vol_sold.text()


# ── Carton SKU ───────────────────────────────────────────────────────────────

class TestCartonSku:
    def test_defaults_to_placeholder_when_unset(self, product_edit_view):
        assert product_edit_view.lbl_carton_sku.text() == "—"

    def test_row_sits_between_barcode_and_description(self, product_edit_view):
        from PyQt6.QtWidgets import QLabel
        texts = [lbl.text() for lbl in product_edit_view.findChildren(QLabel)]
        assert texts.index("Barcode") < texts.index("Carton SKU") < texts.index("Description")

    def test_loads_existing_value(self, qtbot, test_db, db_conn, dept_id, supplier_id):
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, supplier_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit, carton_sku) "
            "VALUES ('8000000000030', 'Carton Item', ?, ?, 5.00, 2.00, 10.0, 1, 1, 'EA', 'CTN-9001')",
            (dept_id, supplier_id)
        )
        db_conn.commit()
        from views.products.product_edit import ProductEdit
        w = ProductEdit('8000000000030')
        qtbot.addWidget(w)
        assert w._carton_sku == "CTN-9001"
        assert w.lbl_carton_sku.text() == "CTN-9001"

    def test_edit_updates_value_and_label(self, product_edit_view):
        with patch('views.products.product_edit.text_popup_optional', return_value="CTN-4455"):
            product_edit_view._edit_carton_sku()
        assert product_edit_view._carton_sku == "CTN-4455"
        assert product_edit_view.lbl_carton_sku.text() == "CTN-4455"

    def test_edit_cancelled_leaves_value_unchanged(self, product_edit_view):
        product_edit_view._carton_sku = "CTN-ORIGINAL"
        with patch('views.products.product_edit.text_popup_optional', return_value=None):
            product_edit_view._edit_carton_sku()
        assert product_edit_view._carton_sku == "CTN-ORIGINAL"

    def test_edit_clearing_shows_placeholder(self, product_edit_view):
        product_edit_view._carton_sku = "CTN-ORIGINAL"
        with patch('views.products.product_edit.text_popup_optional', return_value=""):
            product_edit_view._edit_carton_sku()
        assert product_edit_view._carton_sku == ""
        assert product_edit_view.lbl_carton_sku.text() == "—"


# ── Unit ─────────────────────────────────────────────────────────────────────

class TestEditUnit:
    def test_choice_list_is_lower_case(self, product_edit_view):
        with patch('views.products.product_edit.choice_popup', return_value=None) as mock_popup:
            product_edit_view._edit_unit()
        options = mock_popup.call_args[0][2]
        assert options == ['ea', 'kg', 'l', 'pk', 'ctn', 'g', 'ml']

    def test_selecting_a_unit_stores_it_lower_case(self, product_edit_view):
        with patch('views.products.product_edit.choice_popup', return_value='kg'):
            product_edit_view._edit_unit()
        assert product_edit_view._unit == 'kg'
        assert product_edit_view.lbl_unit.text() == 'kg'

    def test_legacy_upper_case_value_still_pre_selects_correctly(
        self, qtbot, test_db, db_conn, dept_id, supplier_id
    ):
        """Regression: a product saved before the choice list was
        lower-cased may still have unit='KG' in the DB. The popup must
        still pre-select the matching item (now 'kg'), not silently fall
        back to whatever the first item in the list happens to be."""
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, supplier_id, "
            "sell_price, cost_price, tax_rate, pack_qty, active, unit) "
            "VALUES ('8000000000040', 'Legacy Unit Item', ?, ?, 5.00, 2.00, 10.0, 1, 1, 'KG')",
            (dept_id, supplier_id)
        )
        db_conn.commit()
        from views.products.product_edit import ProductEdit
        w = ProductEdit('8000000000040')
        qtbot.addWidget(w)
        assert w._unit == 'KG'
        with patch('views.products.product_edit.choice_popup', return_value=None) as mock_popup:
            w._edit_unit()
        current_arg = mock_popup.call_args[0][3]
        assert current_arg == 'kg'

    def test_manage_suppliers_table_pre_selects_legacy_upper_case_pack_unit(
        self, qtbot, test_db, db_conn, dept_id, supplier_id, product_barcode
    ):
        """Same regression as above, for the per-supplier Unit combo in the
        Manage Suppliers table."""
        from PyQt6.QtWidgets import QDialog, QComboBox
        db_conn.execute(
            "INSERT INTO product_suppliers (barcode, supplier_id, is_default, pack_unit) "
            "VALUES (?, ?, 1, 'KG')",
            (product_barcode, supplier_id)
        )
        db_conn.commit()

        from views.products.product_edit import ProductEdit
        w = ProductEdit(product_barcode)
        qtbot.addWidget(w)

        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", fake_exec):
            w._edit_supplier()
        combo = captured['dlg'].findChild(QComboBox)
        assert combo.currentText() == 'kg'
        captured['dlg'].close()


# ── _save ─────────────────────────────────────────────────────────────────────

class TestSave:
    def test_changed_values_persist_to_db(self, product_edit_view, product_barcode):
        product_edit_view._description = "Updated Description"
        product_edit_view._sell_price = 12.34
        product_edit_view._carton_sku = "CTN-4455"

        product_edit_view._save()

        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row['description'] == "Updated Description"
        assert row['sell_price'] == pytest.approx(12.34)
        assert row['carton_sku'] == "CTN-4455"

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


# ── Selling-unit popups ──────────────────────────────────────────────────────────

class TestSellingUnitPopups:
    """Regression coverage for the money_field() import used by these popups
    (see v2.16.0-era NameError: 'money_field' not defined when building
    the Sell Price row)."""

    def test_add_selling_unit_popup_opens(self, product_edit_view, qtbot, monkeypatch):
        from PyQt6.QtWidgets import QDialog
        monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        product_edit_view._add_selling_unit_popup()

    def test_edit_selling_unit_popup_opens(self, qtbot, monkeypatch, test_db, dept_id, supplier_id, product_barcode):
        from PyQt6.QtWidgets import QDialog
        monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        su_barcode = '9300000099781'
        product_ctrl.add_product(
            su_barcode, 'Selling Unit Product', dept_id,
            supplier_id=supplier_id, sell_price=2.00, cost_price=1.00, tax_rate=10.0,
        )
        product_ctrl.add_selling_unit(product_barcode, su_barcode, '7003', 'Half', 0.5, 2.00)
        from views.products.product_edit import ProductEdit
        w = ProductEdit(product_barcode)
        qtbot.addWidget(w)
        su_id = product_ctrl.get_selling_units(product_barcode)[0]['id']
        w._edit_selling_unit_popup(su_id)


# ── Full-transaction receipt popup ────────────────────────────────────────────

class TestViewTransactionPopup:
    @staticmethod
    def _capture_exec(monkeypatch, app):
        """Monkeypatch QDialog.exec to capture the exact instance it's
        called on (rather than hunting QApplication.topLevelWidgets() by
        title, which can pick up a stale dialog left open by an earlier
        test — _view_transaction_popup's dialog isn't deleteOnClose)."""
        from PyQt6.QtWidgets import QDialog
        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            self.show()
            app.processEvents()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        return captured

    def test_opens_for_known_reference(self, product_edit_view, qtbot, monkeypatch,
                                        product_barcode):
        import controllers.sales_report_controller as sr_ctrl
        captured = self._capture_exec(monkeypatch, QApplication.instance())
        sr_ctrl.record_pos_sale(
            'RCPT-UI-001', '2026-05-01', 'ash',
            [{'barcode': product_barcode, 'qty': 1, 'line_total': 2.50,
              'description': 'Half Cantaloupe', 'unit_price': 2.50}],
            payment_method='CASH', subtotal=2.50, gst_amount=0.0, total=2.50,
        )
        product_edit_view._view_transaction_popup(product_edit_view, 'RCPT-UI-001')
        assert captured['dlg'].windowTitle() == "Receipt — RCPT-UI-001"
        captured['dlg'].close()

    def test_print_receipt_button_opens_generated_pdf(
        self, product_edit_view, qtbot, monkeypatch, tmp_path
    ):
        from PyQt6.QtWidgets import QPushButton
        import controllers.sales_report_controller as sr_ctrl
        captured = self._capture_exec(monkeypatch, QApplication.instance())
        sr_ctrl.record_pos_sale(
            'RCPT-UI-PRINT-001', '2026-05-01', 'ash',
            [{'barcode': product_edit_view.barcode, 'qty': 1, 'line_total': 2.50,
              'description': 'Half Cantaloupe', 'unit_price': 2.50}],
        )
        opened = []
        with patch('utils.open_file.open_with_default_app', lambda p: opened.append(p)):
            product_edit_view._view_transaction_popup(product_edit_view, 'RCPT-UI-PRINT-001')
            receipt_dlg = captured['dlg']
            print_btn = next(
                b for b in receipt_dlg.findChildren(QPushButton) if "Print" in b.text()
            )
            print_btn.click()
        receipt_dlg.close()
        assert len(opened) == 1
        assert os.path.exists(opened[0])

    def test_print_receipt_failure_shows_error_not_crash(
        self, product_edit_view, qtbot, monkeypatch
    ):
        from PyQt6.QtWidgets import QPushButton
        import controllers.sales_report_controller as sr_ctrl
        captured = self._capture_exec(monkeypatch, QApplication.instance())
        sr_ctrl.record_pos_sale(
            'RCPT-UI-PRINT-002', '2026-05-01', 'ash',
            [{'barcode': product_edit_view.barcode, 'qty': 1, 'line_total': 2.50,
              'description': 'Half Cantaloupe', 'unit_price': 2.50}],
        )
        with patch('controllers.product_controller.generate_receipt_pdf',
                    side_effect=OSError("disk full")), \
             patch('views.products.product_edit.show_error') as mock_show_error:
            product_edit_view._view_transaction_popup(product_edit_view, 'RCPT-UI-PRINT-002')
            receipt_dlg = captured['dlg']
            print_btn = next(
                b for b in receipt_dlg.findChildren(QPushButton) if "Print" in b.text()
            )
            print_btn.click()
        receipt_dlg.close()
        mock_show_error.assert_called_once()

    def test_unknown_reference_shows_message_not_dialog(self, product_edit_view, qtbot):
        with patch('views.products.product_edit.QMessageBox') as mock_mb, \
             patch('views.products.product_edit.QDialog') as mock_dialog:
            product_edit_view._view_transaction_popup(product_edit_view, 'NO-SUCH-REF')
            mock_mb.information.assert_called_once()
            mock_dialog.assert_not_called()

    def test_movement_history_double_click_opens_receipt(
        self, product_edit_view, qtbot, monkeypatch
    ):
        from PyQt6.QtWidgets import QDialog, QTableWidget
        import controllers.sales_report_controller as sr_ctrl
        sr_ctrl.record_pos_sale(
            'RCPT-UI-002', '2026-05-01', 'ash',
            [{'barcode': product_edit_view.barcode, 'qty': 1, 'line_total': 2.50,
              'description': 'Half Cantaloupe', 'unit_price': 2.50}],
        )
        opened = {}

        def fake_exec(self):
            opened['dlg'] = self
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        with patch.object(product_edit_view, '_view_transaction_popup') as mock_popup:
            product_edit_view._view_history()
            dlg = opened['dlg']
            tbl = dlg.findChild(QTableWidget)
            assert tbl.item(0, 1).text() == "SALE"
            tbl.cellDoubleClicked.emit(0, 1)
            mock_popup.assert_called_once_with(dlg, 'RCPT-UI-002')
        dlg.close()


# ── Shelf-edge label printing ───────────────────────────────────────────────────

class TestPrintLabel:
    def test_no_printer_configured_falls_back_to_pdf_dialog(
        self, product_edit_view, qtbot, monkeypatch
    ):
        from PyQt6.QtWidgets import QDialog
        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        product_edit_view._print_label()
        assert captured['dlg'].windowTitle() == "Print Shelf Label"

    def test_printer_configured_prints_direct_without_dialog(
        self, product_edit_view, qtbot, monkeypatch
    ):
        import models.settings as settings_model
        settings_model.set_setting('label_printer_name', 'Zebra GK420D')
        with patch('utils.label_print.print_label_direct',
                    return_value=(True, "Printed")) as mock_print:
            product_edit_view._print_label()
        mock_print.assert_called_once()

    def test_direct_print_failure_shows_error(self, product_edit_view, qtbot, monkeypatch):
        """A real failure from the print call (not a "printer not found"
        message) is surfaced as an error rather than silently falling back
        to a PDF."""
        import models.settings as settings_model
        settings_model.set_setting('label_printer_name', 'Zebra GK420D')
        with patch('utils.label_print.print_label_direct',
                    return_value=(False, "Could not render the label.")), \
             patch('views.products.product_edit.show_error') as mock_show_error:
            product_edit_view._print_label()
        mock_show_error.assert_called_once()

    def test_configured_but_not_found_falls_back_to_pdf(
        self, product_edit_view, qtbot, monkeypatch
    ):
        """Printer name is configured but the direct print reports it isn't
        currently available (unplugged/renamed) — falls back to the PDF
        dialog instead of showing an error, same as if nothing were
        configured at all."""
        import models.settings as settings_model
        from PyQt6.QtWidgets import QDialog
        settings_model.set_setting('label_printer_name', 'Zebra GK420D')
        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        with patch('utils.label_print.print_label_direct',
                    return_value=(False, "Printer 'Zebra GK420D' is not available — "
                                  "check it's connected, or choose a different one "
                                  "in Settings > Label Printing.")) as mock_print, \
             patch('views.products.product_edit.show_error') as mock_show_error:
            product_edit_view._print_label()
        mock_print.assert_called_once()
        mock_show_error.assert_not_called()
        assert captured['dlg'].windowTitle() == "Print Shelf Label"


# ── Edikio card printing ──────────────────────────────────────────────────────

class TestPrintEdikioLabel:
    def test_button_present_and_separate_from_zebra_buttons(self, product_edit_view):
        from PyQt6.QtWidgets import QPushButton
        texts = [b.text() for b in product_edit_view.findChildren(QPushButton)]
        assert "🖨 Print Edikio Card" in texts
        assert "🖨 Print Label" in texts
        assert "🖨 Print Large Label" in texts

    def test_no_printer_configured_falls_back_to_pdf_dialog(
        self, product_edit_view, qtbot, monkeypatch
    ):
        from PyQt6.QtWidgets import QDialog
        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        product_edit_view._print_edikio_label()
        assert captured['dlg'].windowTitle() == "Print Edikio Card"

    def test_printer_configured_prints_direct_without_dialog(
        self, product_edit_view, qtbot, monkeypatch
    ):
        import models.settings as settings_model
        settings_model.set_setting('edikio_printer_name', 'Edikio Access')
        with patch('utils.label_print.print_edikio_label_direct',
                    return_value=(True, "Printed")) as mock_print:
            product_edit_view._print_edikio_label()
        mock_print.assert_called_once()
        _, kwargs = mock_print.call_args
        assert kwargs['barcode'] == product_edit_view.barcode
        assert kwargs['unit'] == product_edit_view._unit
        assert 'plu' not in kwargs

    def test_direct_print_failure_shows_error(self, product_edit_view, qtbot, monkeypatch):
        """A real failure from the print call (not a "printer not found"
        message) is surfaced as an error rather than silently falling back
        to a PDF."""
        import models.settings as settings_model
        settings_model.set_setting('edikio_printer_name', 'Edikio Access')
        with patch('utils.label_print.print_edikio_label_direct',
                    return_value=(False, "Printer offline")), \
             patch('views.products.product_edit.show_error') as mock_show_error:
            product_edit_view._print_edikio_label()
        mock_show_error.assert_called_once()

    def test_configured_but_not_found_falls_back_to_pdf(
        self, product_edit_view, qtbot, monkeypatch
    ):
        """Printer name is configured but the direct print reports it isn't
        currently available (unplugged/renamed) — falls back to the PDF
        dialog instead of showing an error, same as if nothing were
        configured at all."""
        import models.settings as settings_model
        from PyQt6.QtWidgets import QDialog
        settings_model.set_setting('edikio_printer_name', 'Edikio Access')
        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        with patch('utils.label_print.print_edikio_label_direct',
                    return_value=(False, "Printer 'Edikio Access' is not available — "
                                  "check it's connected, or choose a different one "
                                  "in Settings > Label Printing.")) as mock_print, \
             patch('views.products.product_edit.show_error') as mock_show_error:
            product_edit_view._print_edikio_label()
        mock_print.assert_called_once()
        mock_show_error.assert_not_called()
        assert captured['dlg'].windowTitle() == "Print Edikio Card"

    def test_pdf_fallback_generates_and_opens_file(
        self, product_edit_view, qtbot, monkeypatch
    ):
        from PyQt6.QtWidgets import QDialog, QPushButton

        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            self.show()
            QApplication.processEvents()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        opened = []
        with patch('utils.open_file.open_with_default_app', lambda p: opened.append(p)):
            product_edit_view._print_edikio_label_via_pdf()
            dlg = captured['dlg']
            print_btn = next(
                b for b in dlg.findChildren(QPushButton) if b.text().startswith("Print")
            )
            print_btn.click()
        dlg.close()
        assert len(opened) == 1
        assert os.path.exists(opened[0])
        os.remove(opened[0])
