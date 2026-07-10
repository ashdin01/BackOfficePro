"""Widget regression tests for POHistory (views/purchase_orders/po_history.py) —
the archived-PO viewer, and specifically _reverse(), which removes
previously-received stock from inventory and cannot be undone.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
import subprocess
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.purchase_order_controller as po_ctrl
import controllers.product_controller as product_ctrl


def _received_po(supplier_id, product_barcode, ordered=10, received=6, unit_cost=2.00):
    po_id = po_ctrl.create_po(supplier_id)
    po_ctrl.add_po_line(po_id, product_barcode, 'Test Product', ordered, unit_cost=unit_cost)
    line = po_ctrl.get_po_lines(po_id)[0]
    po_ctrl.receive_po_atomic(
        po_id, po_ctrl.get_po_by_id(po_id)['po_number'],
        [{'line_id': line['id'], 'barcode': product_barcode, 'new_received_qty': received,
          'actual_cost': unit_cost, 'unit_cost': unit_cost, 'is_promo': False, 'qty_units': received}],
        final_status='RECEIVED',
    )
    return po_id


def _mock_qmessagebox(monkeypatch, warning_return=None):
    import views.purchase_orders.po_history as _mod
    mock_mb = MagicMock(spec=QMessageBox)
    mock_mb.StandardButton = QMessageBox.StandardButton
    if warning_return is not None:
        mock_mb.warning.return_value = warning_return
    monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)
    return mock_mb


# ── Loading / display ────────────────────────────────────────────────────────────

class TestLoad:
    def test_header_shows_po_number_and_status(self, qtbot, test_db, supplier_id, product_barcode):
        pid = _received_po(supplier_id, product_barcode)
        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        po = po_ctrl.get_po_by_id(pid)
        assert po['po_number'] in w.header.text()
        assert 'RECEIVED' in w.header.text()

    def test_lines_table_shows_received_quantity(
        self, qtbot, test_db, supplier_id, product_barcode
    ):
        pid = _received_po(supplier_id, product_barcode, ordered=10, received=6)
        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)

        assert w.table.rowCount() == 1
        assert w.table.item(0, 4).text() == "6"

    def test_totals_reflect_received_lines(self, qtbot, test_db, supplier_id, product_barcode):
        pid = _received_po(supplier_id, product_barcode, received=6, unit_cost=2.00)
        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        # 6 units x $2.00 = $12.00 ex GST
        assert "$12.00" in w.totals_lbl.text()

    def test_bank_details_shown_when_supplier_has_them(
        self, qtbot, test_db, supplier_id, product_barcode
    ):
        import controllers.supplier_controller as supplier_ctrl
        supplier_ctrl.update(
            supplier_id, "TST", "Test Supplier", "", "", "", "", "", "", 1,
            bank_account_name="Acme Bank Account", bank_bsb="063-000",
            bank_account_number="99887766",
        )
        pid = _received_po(supplier_id, product_barcode)
        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)

        assert hasattr(w, 'bank_lbl')
        assert "Acme Bank Account" in w.bank_lbl.text()

    def test_no_bank_details_no_bank_label(self, qtbot, test_db, supplier_id, product_barcode):
        pid = _received_po(supplier_id, product_barcode)
        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        assert not hasattr(w, 'bank_lbl') or w.bank_lbl is None


# ── Reverse button visibility ──────────────────────────────────────────────────

class TestReverseButtonVisibility:
    def test_shown_for_received(self, qtbot, test_db, supplier_id, product_barcode):
        pid = _received_po(supplier_id, product_barcode)
        from views.purchase_orders.po_history import POHistory
        from PyQt6.QtWidgets import QPushButton
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        labels = [b.text() for b in w.findChildren(QPushButton)]
        assert any("Reverse" in t for t in labels)

    def test_hidden_for_draft(self, qtbot, test_db, supplier_id):
        pid = po_ctrl.create_po(supplier_id)
        from views.purchase_orders.po_history import POHistory
        from PyQt6.QtWidgets import QPushButton
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        labels = [b.text() for b in w.findChildren(QPushButton)]
        assert not any("Reverse" in t for t in labels)

    def test_hidden_for_cancelled(self, qtbot, test_db, supplier_id):
        pid = po_ctrl.create_po(supplier_id)
        po_ctrl.update_po_status(pid, 'SENT')
        po_ctrl.cancel_po(pid)
        from views.purchase_orders.po_history import POHistory
        from PyQt6.QtWidgets import QPushButton
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        labels = [b.text() for b in w.findChildren(QPushButton)]
        assert not any("Reverse" in t for t in labels)


# ── _reverse() ─────────────────────────────────────────────────────────────────

class TestReverse:
    def test_nothing_received_shows_info_and_makes_no_change(
        self, qtbot, test_db, supplier_id, product_barcode, monkeypatch
    ):
        po_id = po_ctrl.create_po(supplier_id)
        po_ctrl.add_po_line(po_id, product_barcode, 'Test Product', 10, unit_cost=2.00)
        po_ctrl.update_po_status(po_id, 'PARTIAL')  # zero received, still PARTIAL

        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=po_id)
        qtbot.addWidget(w)
        mock_mb = _mock_qmessagebox(monkeypatch)

        w._reverse()

        mock_mb.information.assert_called_once()
        assert po_ctrl.get_po_by_id(po_id)['status'] == 'PARTIAL'

    def test_declined_confirmation_makes_no_change(
        self, qtbot, test_db, supplier_id, product_barcode, monkeypatch
    ):
        pid = _received_po(supplier_id, product_barcode, received=6)
        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        _mock_qmessagebox(monkeypatch, warning_return=QMessageBox.StandardButton.No)

        w._reverse()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'RECEIVED'

    def test_confirmed_reversal_marks_po_reversed_and_removes_stock(
        self, qtbot, test_db, supplier_id, product_barcode, monkeypatch
    ):
        product_ctrl.adjust_soh(product_barcode, 6, "SEED")
        pid = _received_po(supplier_id, product_barcode, received=6)
        # receive_po_atomic already added 6 units on top of the seeded 6
        before = product_ctrl.get_soh_by_barcode(product_barcode)['quantity']

        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        _mock_qmessagebox(monkeypatch, warning_return=QMessageBox.StandardButton.Yes)

        w._reverse()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'REVERSED'
        after = product_ctrl.get_soh_by_barcode(product_barcode)['quantity']
        assert after == before - 6

    def test_reversal_calls_on_close_and_closes_window(
        self, qtbot, test_db, supplier_id, product_barcode, monkeypatch
    ):
        pid = _received_po(supplier_id, product_barcode, received=6)
        from views.purchase_orders.po_history import POHistory
        on_close = MagicMock()
        w = POHistory(po_id=pid, on_close=on_close)
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()
        _mock_qmessagebox(monkeypatch, warning_return=QMessageBox.StandardButton.Yes)

        w._reverse()
        QApplication.processEvents()

        on_close.assert_called_once()
        assert not w.isVisible()

    def test_reversal_failure_shows_error_not_crash(
        self, qtbot, test_db, supplier_id, product_barcode, monkeypatch
    ):
        pid = _received_po(supplier_id, product_barcode, received=6)
        from views.purchase_orders.po_history import POHistory
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)
        _mock_qmessagebox(monkeypatch, warning_return=QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(
            po_ctrl, "reverse_po",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db locked")),
        )

        with patch('views.purchase_orders.po_history.show_error') as mock_show_error:
            w._reverse()  # must not raise
            mock_show_error.assert_called_once()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'RECEIVED'


# ── Export CSV ────────────────────────────────────────────────────────────────

class TestExportCsv:
    def test_cancelled_file_dialog_writes_nothing(
        self, qtbot, test_db, supplier_id, product_barcode, monkeypatch, tmp_path
    ):
        pid = _received_po(supplier_id, product_barcode)
        from views.purchase_orders.po_history import POHistory
        import views.purchase_orders.po_history as _mod
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)

        monkeypatch.setattr(_mod.QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))

        w._export_csv()  # must not raise, must not attempt to open a subprocess

        assert list(tmp_path.glob("*.csv")) == []

    def test_export_writes_expected_totals_row(
        self, qtbot, test_db, supplier_id, product_barcode, monkeypatch, tmp_path
    ):
        pid = _received_po(supplier_id, product_barcode, received=6, unit_cost=2.00)
        from views.purchase_orders.po_history import POHistory
        import views.purchase_orders.po_history as _mod
        w = POHistory(po_id=pid)
        qtbot.addWidget(w)

        out_path = str(tmp_path / "export.csv")
        monkeypatch.setattr(_mod.QFileDialog, "getSaveFileName", lambda *a, **kw: (out_path, ""))
        # _export_csv does a local `import subprocess` — same module object,
        # so patching the real module (not _mod.subprocess) is what's needed.
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(_mod.os, "startfile", MagicMock(), raising=False)

        w._export_csv()

        content = (tmp_path / "export.csv").read_text()
        assert "Subtotal ex. GST" in content
        assert "12.00" in content
