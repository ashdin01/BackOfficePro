"""
Widget tests for SellingUnitsPanel (views/products/selling_units_panel.py).

Extracted from ProductEdit's _build_selling_units_section/_load_selling_units/
_add_selling_unit_popup/_edit_selling_unit_popup/_remove_selling_unit.
"""
import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

import controllers.product_controller as product_ctrl
from views.products.selling_units_panel import SellingUnitsPanel


@pytest.fixture()
def panel(qtbot, test_db, product_barcode):
    p = SellingUnitsPanel(product_barcode, lambda: 3.50)
    qtbot.addWidget(p)
    p.show()
    QApplication.processEvents()
    return p


class TestLoad:
    def test_no_selling_units_initially(self, panel):
        assert panel.table.rowCount() == 0

    def test_existing_selling_units_populate_table(self, qtbot, test_db, product_barcode):
        product_ctrl.add_selling_unit(product_barcode, None, '134', 'Case of 6', 6, 18.00)
        p = SellingUnitsPanel(product_barcode, lambda: 3.50)
        qtbot.addWidget(p)

        assert p.table.rowCount() == 1
        assert p.table.item(0, 2).text() == 'Case of 6'
        assert p.table.item(0, 4).text() == '$18.00'


class TestAddSellingUnit:
    def test_price_defaults_to_qty_times_live_master_price(self, qtbot, monkeypatch, panel):
        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        panel._add_selling_unit_popup()

        from PyQt6.QtWidgets import QDoubleSpinBox
        spins = captured['dlg'].findChildren(QDoubleSpinBox)
        qty_spin, price_spin = spins[0], spins[1]
        assert qty_spin.value() == 6
        assert price_spin.value() == pytest.approx(3.50 * 6)

    def test_uses_current_callback_value_not_stale_snapshot(self, qtbot, monkeypatch, test_db, product_barcode):
        """Regression: price must reflect the *current* master sell price at
        popup-open time, in case it changed since the panel was constructed —
        this is exactly why the panel takes a callable, not a fixed number."""
        current_price = {'value': 3.50}
        p = SellingUnitsPanel(product_barcode, lambda: current_price['value'])
        qtbot.addWidget(p)
        current_price['value'] = 10.00  # simulate the user editing Sell Price afterwards

        captured = {}

        def fake_exec(self):
            captured['dlg'] = self
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        p._add_selling_unit_popup()

        from PyQt6.QtWidgets import QDoubleSpinBox
        price_spin = captured['dlg'].findChildren(QDoubleSpinBox)[1]
        assert price_spin.value() == pytest.approx(60.00)

    def test_add_persists_and_reloads_table(self, qtbot, monkeypatch, panel):
        def fake_exec(self):
            from PyQt6.QtWidgets import QLineEdit, QDoubleSpinBox, QPushButton
            self.findChildren(QLineEdit)[0].setText("Six Pack")
            ok_btn = [b for b in self.findChildren(QPushButton) if b.text().startswith('Add')][0]
            ok_btn.click()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        panel._add_selling_unit_popup()

        assert panel.table.rowCount() == 1
        assert panel.table.item(0, 2).text() == "Six Pack"

    def test_blank_label_shows_validation_warning(self, qtbot, monkeypatch, panel):
        mock_warn = MagicMock()
        monkeypatch.setattr(QMessageBox, "warning", mock_warn)

        def fake_exec(self):
            from PyQt6.QtWidgets import QPushButton
            ok_btn = [b for b in self.findChildren(QPushButton) if b.text().startswith('Add')][0]
            ok_btn.click()
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        panel._add_selling_unit_popup()

        mock_warn.assert_called_once()
        assert panel.table.rowCount() == 0


class TestEditAndRemove:
    def test_edit_updates_persisted_values(self, qtbot, monkeypatch, test_db, product_barcode):
        product_ctrl.add_selling_unit(product_barcode, None, '134', 'Case of 6', 6, 18.00)
        p = SellingUnitsPanel(product_barcode, lambda: 3.50)
        qtbot.addWidget(p)
        su_id = product_ctrl.get_selling_units(product_barcode)[0]['id']

        def fake_exec(self):
            from PyQt6.QtWidgets import QLineEdit, QPushButton
            self.findChildren(QLineEdit)[0].setText("Case of Twelve")
            ok_btn = [b for b in self.findChildren(QPushButton) if b.text().startswith('Save')][0]
            ok_btn.click()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        p._edit_selling_unit_popup(su_id)

        assert p.table.item(0, 2).text() == "Case of Twelve"
        assert product_ctrl.get_selling_unit_by_id(su_id)['label'] == "Case of Twelve"

    def test_remove_confirmed_deletes_and_reloads(self, qtbot, monkeypatch, test_db, product_barcode):
        product_ctrl.add_selling_unit(product_barcode, None, '134', 'Case of 6', 6, 18.00)
        p = SellingUnitsPanel(product_barcode, lambda: 3.50)
        qtbot.addWidget(p)
        su_id = product_ctrl.get_selling_units(product_barcode)[0]['id']

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        p._remove_selling_unit(su_id)

        assert p.table.rowCount() == 0
        assert product_ctrl.get_selling_unit_by_id(su_id) is None

    def test_remove_declined_keeps_row(self, qtbot, monkeypatch, test_db, product_barcode):
        product_ctrl.add_selling_unit(product_barcode, None, '134', 'Case of 6', 6, 18.00)
        p = SellingUnitsPanel(product_barcode, lambda: 3.50)
        qtbot.addWidget(p)
        su_id = product_ctrl.get_selling_units(product_barcode)[0]['id']

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )
        p._remove_selling_unit(su_id)

        assert p.table.rowCount() == 1
        assert product_ctrl.get_selling_unit_by_id(su_id) is not None
