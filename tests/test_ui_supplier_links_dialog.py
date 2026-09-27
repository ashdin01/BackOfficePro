"""
Widget tests for SupplierLinksDialog (views/products/supplier_links_dialog.py).

Extracted from ProductEdit's _edit_supplier/_refresh_sup_table/etc. — these
tests exercise it directly, with plain-Python fixtures (no DB), which the
extraction is what makes possible.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton, QLineEdit, QDialog, QMessageBox

from views.products.supplier_links_dialog import SupplierLinksDialog


def _suppliers():
    return [
        {'id': 1, 'name': 'Istra Foods'},
        {'id': 2, 'name': 'Bulla Dairy'},
    ]


def _product_suppliers():
    return [
        {'supplier_id': 1, 'supplier_name': 'Istra Foods', 'is_default': True,
         'supplier_sku': 'IST-100', 'pack_qty': 6, 'pack_unit': 'ea', 'last_cost': 2.50},
    ]


@pytest.fixture()
def dialog(qtbot):
    links = _product_suppliers()
    dlg = SupplierLinksDialog(links, _suppliers(), read_only=False)
    qtbot.addWidget(dlg)
    dlg.show()
    QApplication.processEvents()
    dlg._links_ref = links  # keep the same list object handy for assertions
    return dlg


class TestTablePopulation:
    def test_one_row_per_linked_supplier(self, dialog):
        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 0).text() == 'Istra Foods'

    def test_last_cost_shown_formatted(self, dialog):
        assert dialog.table.item(0, 4).text() == '$2.5000'

    def test_default_supplier_shows_disabled_default_button(self, dialog):
        btn = dialog.table.cellWidget(0, 5)
        assert isinstance(btn, QPushButton)
        assert btn.text() == '★ Default'
        assert not btn.isEnabled()


class TestAddSupplier:
    def test_add_supplier_appends_to_shared_list(self, qtbot, dialog):
        combo = None

        def fake_exec(self):
            nonlocal combo
            combo = self.findChild(QComboBox)
            combo.setCurrentIndex(0)  # only 'Bulla Dairy' is available
            sku = self.findChild(QLineEdit)
            sku.setText('BUL-9')
            ok_btn = [b for b in self.findChildren(QPushButton) if b.text().startswith('Add')][0]
            ok_btn.click()

        with patch.object(QDialog, 'exec', fake_exec):
            dialog._add_supplier_popup()

        assert len(dialog._links_ref) == 2
        assert dialog._links_ref[1]['supplier_id'] == 2
        assert dialog._links_ref[1]['supplier_sku'] == 'BUL-9'
        assert dialog.table.rowCount() == 2

    def test_all_suppliers_already_linked_shows_info_message(self, qtbot, monkeypatch, dialog):
        dialog._links_ref.append({
            'supplier_id': 2, 'supplier_name': 'Bulla Dairy', 'is_default': False,
            'supplier_sku': '', 'pack_qty': 1, 'pack_unit': 'ea', 'last_cost': None,
        })
        mock_info = MagicMock()
        monkeypatch.setattr(QMessageBox, 'information', mock_info)

        dialog._add_supplier_popup()

        mock_info.assert_called_once()


class TestRemoveAndDefault:
    def test_removing_default_promotes_next_row_to_default(self, dialog):
        dialog._links_ref.append({
            'supplier_id': 2, 'supplier_name': 'Bulla Dairy', 'is_default': False,
            'supplier_sku': '', 'pack_qty': 1, 'pack_unit': 'ea', 'last_cost': None,
        })
        dialog._refresh_table()

        dialog._remove_supplier(0)

        assert len(dialog._links_ref) == 1
        assert dialog._links_ref[0]['supplier_id'] == 2
        assert dialog._links_ref[0]['is_default'] is True

    def test_set_default_clears_previous_default(self, dialog):
        dialog._links_ref.append({
            'supplier_id': 2, 'supplier_name': 'Bulla Dairy', 'is_default': False,
            'supplier_sku': '', 'pack_qty': 1, 'pack_unit': 'ea', 'last_cost': None,
        })
        dialog._refresh_table()

        dialog._set_default_supplier(1)

        assert dialog._links_ref[0]['is_default'] is False
        assert dialog._links_ref[1]['is_default'] is True


class TestReadOnlyMode:
    def test_read_only_hides_add_and_remove_buttons(self, qtbot):
        dlg = SupplierLinksDialog(_product_suppliers(), _suppliers(), read_only=True)
        qtbot.addWidget(dlg)
        dlg.show()
        QApplication.processEvents()

        add_buttons = [b for b in dlg.findChildren(QPushButton) if b.text() == '+ Add Supplier']
        assert add_buttons == []
        assert dlg.table.cellWidget(0, 6) is None  # no remove button

    def test_read_only_shows_plain_text_cells_not_editors(self, qtbot):
        dlg = SupplierLinksDialog(_product_suppliers(), _suppliers(), read_only=True)
        qtbot.addWidget(dlg)
        dlg.show()
        QApplication.processEvents()

        assert dlg.table.cellWidget(0, 1) is None
        assert dlg.table.item(0, 1).text() == 'IST-100'
