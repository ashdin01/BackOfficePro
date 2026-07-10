"""Widget regression tests for POCreate (views/purchase_orders/po_create.py).

Covers the fix for: the supplier field used to be a QComboBox that always
had *something* selected (alphabetically first), so it was easy to create
a PO for the wrong supplier without noticing. Supplier must now be
actively picked via the F3 lookup dialog before an order can be created.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.purchase_order_controller as po_ctrl
import controllers.supplier_controller as supplier_ctrl


@pytest.fixture()
def two_suppliers(db_conn):
    """Two suppliers, deliberately named so alphabetical-first != the one
    the test actually picks — proves the fix isn't defaulting silently."""
    db_conn.execute("INSERT INTO suppliers (code, name) VALUES ('AAA', 'AAA Supplier')")
    db_conn.execute("INSERT INTO suppliers (code, name) VALUES ('ZZZ', 'ZZZ Supplier')")
    db_conn.commit()
    aaa_id = db_conn.execute("SELECT id FROM suppliers WHERE code='AAA'").fetchone()["id"]
    zzz_id = db_conn.execute("SELECT id FROM suppliers WHERE code='ZZZ'").fetchone()["id"]
    return {"aaa_id": aaa_id, "zzz_id": zzz_id}


@pytest.fixture()
def po_create_view(qtbot, test_db, two_suppliers):
    from views.purchase_orders.po_create import POCreate
    widget = POCreate()
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


# ── No supplier chosen yet ─────────────────────────────────────────────────────

class TestNoSupplierSelected:
    def test_label_shows_warning_state(self, po_create_view):
        assert "no supplier" in po_create_view.supplier_lbl.text().lower()

    def test_create_buttons_disabled(self, po_create_view):
        assert not po_create_view.rec_btn.isEnabled()
        assert not po_create_view.blank_btn.isEnabled()

    def test_save_blocked_with_warning(self, po_create_view, monkeypatch):
        import views.purchase_orders.po_create as _mod
        mock_mb = MagicMock(spec=QMessageBox)
        monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)
        create_spy = MagicMock(wraps=po_ctrl.create_po)
        monkeypatch.setattr(po_ctrl, 'create_po', create_spy)
        # _save()'s guard follows the warning by opening the real F3 picker —
        # useful in the app, but this test is only about the guard itself.
        monkeypatch.setattr(po_create_view, '_select_supplier', MagicMock())

        po_create_view._save(blank=True)

        mock_mb.warning.assert_called_once()
        create_spy.assert_not_called()


# ── Active selection via the F3 lookup ─────────────────────────────────────────

class TestSupplierLookup:
    def test_selecting_updates_label_and_enables_buttons(
        self, po_create_view, two_suppliers
    ):
        from views.purchase_orders.po_create import _SupplierLookup
        dlg = _SupplierLookup(po_create_view)
        # Pick the ZZZ supplier explicitly (not row 0 / alphabetically first)
        row = next(r for r in range(dlg.table.rowCount())
                   if dlg.table.item(r, 0).text() == 'ZZZ')
        dlg.table.selectRow(row)
        dlg._pick()

        assert dlg.selected_id == two_suppliers['zzz_id']

        po_create_view._supplier_id = dlg.selected_id
        po_create_view._supplier_name = dlg.selected_name
        po_create_view._refresh_supplier_label()

        assert "ZZZ Supplier" in po_create_view.supplier_lbl.text()
        assert po_create_view.blank_btn.isEnabled()

    def test_search_filters_by_name_or_code(self, po_create_view, two_suppliers):
        from views.purchase_orders.po_create import _SupplierLookup
        dlg = _SupplierLookup(po_create_view)
        dlg.search.setText("ZZZ")
        dlg._filter()
        names = [dlg.table.item(r, 1).text() for r in range(dlg.table.rowCount())]
        assert names == ["ZZZ Supplier"]

    def test_cancelling_lookup_leaves_supplier_unselected(self, po_create_view):
        assert po_create_view._supplier_id is None
        with patch('views.purchase_orders.po_create._SupplierLookup') as MockDlg:
            instance = MockDlg.return_value
            instance.exec.return_value = 0  # QDialog.DialogCode.Rejected
            po_create_view._select_supplier()
        assert po_create_view._supplier_id is None
        assert not po_create_view.blank_btn.isEnabled()


# ── Preset supplier (opened from a supplier's own context) ────────────────────

class TestPresetSupplier:
    def test_preset_supplier_prefilled_and_enabled(self, qtbot, test_db, two_suppliers):
        from views.purchase_orders.po_create import POCreate
        w = POCreate(supplier_id=two_suppliers['aaa_id'])
        qtbot.addWidget(w)

        assert w._supplier_id == two_suppliers['aaa_id']
        assert "AAA Supplier" in w.supplier_lbl.text()
        assert w.blank_btn.isEnabled()


# ── Successful creation uses the actively-picked supplier ─────────────────────

class TestSaveWithSupplierSelected:
    def test_blank_order_created_for_the_picked_supplier_not_the_first(
        self, po_create_view, two_suppliers
    ):
        """Regression: previously this always created the PO for whichever
        supplier happened to sort first alphabetically."""
        po_create_view._supplier_id = two_suppliers['zzz_id']
        po_create_view._supplier_name = 'ZZZ Supplier'
        po_create_view._refresh_supplier_label()

        with patch('views.purchase_orders.po_detail.PODetail') as MockDetail:
            MockDetail.return_value = MagicMock()
            po_create_view._save(blank=True)

        pos = po_ctrl.get_all_pos(status='DRAFT')
        assert len(pos) == 1
        assert pos[0]['supplier_id'] == two_suppliers['zzz_id']

    def test_invalid_order_type_still_blocks_save(self, po_create_view, two_suppliers, monkeypatch):
        po_create_view._supplier_id = two_suppliers['aaa_id']
        po_create_view._supplier_name = 'AAA Supplier'
        po_create_view._refresh_supplier_label()
        po_create_view.type_input.setText('ZZ')  # not a real type

        import views.purchase_orders.po_create as _mod
        mock_mb = MagicMock(spec=QMessageBox)
        monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)
        create_spy = MagicMock(wraps=po_ctrl.create_po)
        monkeypatch.setattr(po_ctrl, 'create_po', create_spy)

        po_create_view._save(blank=True)

        mock_mb.warning.assert_called_once()
        create_spy.assert_not_called()
