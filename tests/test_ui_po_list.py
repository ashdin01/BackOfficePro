"""Widget regression tests for POList (views/purchase_orders/po_list.py) —
the main Purchase Orders screen: active/archive tabs, and the guard clauses
around receiving, updating, cancelling, and force-closing an order.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.purchase_order_controller as po_ctrl


def _make_po(supplier_id, status='DRAFT', po_type='PO'):
    po_id = po_ctrl.create_po(supplier_id, po_type=po_type)
    if status != 'DRAFT':
        po_ctrl.update_po_status(po_id, status)
    return po_id


def _select_row(table, po_id):
    for r in range(table.rowCount()):
        if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == po_id:
            table.selectRow(r)
            return
    raise AssertionError(f"po_id {po_id} not found in table")


@pytest.fixture()
def po_list_view(qtbot, test_db, supplier_id):
    from views.purchase_orders.po_list import POList
    widget = POList()
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _mock_qmessagebox(monkeypatch, question_return=None, warning_return=None):
    import views.purchase_orders.po_list as _mod
    mock_mb = MagicMock(spec=QMessageBox)
    mock_mb.StandardButton = QMessageBox.StandardButton
    if question_return is not None:
        mock_mb.question.return_value = question_return
    if warning_return is not None:
        mock_mb.warning.return_value = warning_return
    monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)
    return mock_mb


# ── Startup cleanup ───────────────────────────────────────────────────────────

class TestStartupCleanup:
    def test_cleanup_called_on_construction(self, qtbot, test_db, monkeypatch):
        spy = MagicMock(wraps=po_ctrl.cleanup_old_pos)
        monkeypatch.setattr(po_ctrl, 'cleanup_old_pos', spy)
        from views.purchase_orders.po_list import POList
        w = POList()
        qtbot.addWidget(w)
        spy.assert_called_once()

    def test_cleanup_failure_does_not_crash_widget(self, qtbot, test_db, monkeypatch):
        monkeypatch.setattr(
            po_ctrl, 'cleanup_old_pos',
            lambda: (_ for _ in ()).throw(RuntimeError("db locked")),
        )
        from views.purchase_orders.po_list import POList
        w = POList()  # must not raise
        qtbot.addWidget(w)


# ── Loading ───────────────────────────────────────────────────────────────────

class TestLoad:
    def test_active_table_lists_non_archived_pos(self, po_list_view, supplier_id):
        _make_po(supplier_id, status='SENT')
        po_list_view.load()
        assert po_list_view.active_table.rowCount() == 1

    def test_received_po_not_in_active_table(self, po_list_view, supplier_id):
        _make_po(supplier_id, status='RECEIVED')
        po_list_view.load()
        assert po_list_view.active_table.rowCount() == 0

    def test_archive_tab_lists_received_and_cancelled(self, po_list_view, supplier_id):
        _make_po(supplier_id, status='RECEIVED')
        _make_po(supplier_id, status='CANCELLED')
        po_list_view._load_archive()
        assert po_list_view.archive_table.rowCount() == 2

    def test_archive_filter_narrows_to_status(self, po_list_view, supplier_id):
        _make_po(supplier_id, status='RECEIVED')
        _make_po(supplier_id, status='CANCELLED')
        idx = po_list_view.archive_filter.findData('CANCELLED')
        po_list_view.archive_filter.setCurrentIndex(idx)
        assert po_list_view.archive_table.rowCount() == 1
        assert po_list_view.archive_table.item(0, 3).text() == 'CANCELLED'


# ── Selection helpers ─────────────────────────────────────────────────────────

class TestSelectionHelpers:
    def test_no_selection_returns_none(self, po_list_view):
        po_list_view.active_table.clearSelection()
        po_list_view.active_table.setCurrentCell(-1, -1)
        po_id, status = po_list_view._get_selected()
        assert po_id is None and status is None

    def test_selected_row_returns_id_and_status(self, po_list_view, supplier_id):
        pid = _make_po(supplier_id, status='SENT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        got_id, status = po_list_view._get_selected()
        assert got_id == pid
        assert status == 'SENT'


# ── _open_receive guards ───────────────────────────────────────────────────────

class TestOpenReceive:
    def test_no_selection_shows_info(self, po_list_view, monkeypatch):
        po_list_view.active_table.clearSelection()
        po_list_view.active_table.setCurrentCell(-1, -1)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._open_receive()
        mock_mb.information.assert_called_once()

    def test_draft_po_cannot_be_received(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='DRAFT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._open_receive()
        mock_mb.information.assert_called_once()

    def test_sent_po_opens_po_receive(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='SENT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        import views.purchase_orders.po_receive as _recv_mod
        mock_cls = MagicMock()
        monkeypatch.setattr(_recv_mod, 'POReceive', mock_cls)
        po_list_view._open_receive()
        mock_cls.assert_called_once_with(po_id=pid, on_save=po_list_view._load)

    def test_ro_type_requires_sent_status(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='DRAFT', po_type='RO')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._open_receive()
        mock_mb.information.assert_called_once()

    def test_ro_type_sent_opens_credit_close(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='SENT', po_type='RO')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        import views.purchase_orders.credit_close as _cc_mod
        mock_cls = MagicMock()
        monkeypatch.setattr(_cc_mod, 'CreditClose', mock_cls)
        po_list_view._open_receive()
        mock_cls.assert_called_once_with(po_id=pid, on_save=po_list_view._load)


# ── _update_po guards ──────────────────────────────────────────────────────────

class TestUpdatePo:
    def test_no_selection_shows_info(self, po_list_view, monkeypatch):
        po_list_view.active_table.clearSelection()
        po_list_view.active_table.setCurrentCell(-1, -1)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._update_po()
        mock_mb.information.assert_called_once()

    def test_non_partial_po_blocked(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='SENT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._update_po()
        mock_mb.information.assert_called_once()
        assert po_ctrl.get_po_by_id(pid)['status'] == 'SENT'

    def test_partial_with_zero_received_blocked(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='PARTIAL')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._update_po()
        mock_mb.warning.assert_called_once()
        assert po_ctrl.get_po_by_id(pid)['status'] == 'PARTIAL'

    def test_confirmed_update_sets_received(
        self, po_list_view, supplier_id, product_barcode, monkeypatch
    ):
        pid = _make_po(supplier_id, status='SENT')
        po_ctrl.add_po_line(pid, product_barcode, 'Test Product', 10, unit_cost=2.00)
        line = po_ctrl.get_po_lines(pid)[0]
        po_ctrl.receive_po_atomic(
            pid, po_ctrl.get_po_by_id(pid)['po_number'],
            [{'line_id': line['id'], 'barcode': product_barcode, 'new_received_qty': 3,
              'actual_cost': 2.00, 'unit_cost': 2.00, 'is_promo': False, 'qty_units': 3}],
            final_status='PARTIAL',
        )
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        mock_mb = _mock_qmessagebox(
            monkeypatch, question_return=QMessageBox.StandardButton.Yes
        )

        po_list_view._update_po()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'RECEIVED'
        mock_mb.information.assert_called_once()

    def test_declined_confirmation_leaves_status_unchanged(
        self, po_list_view, supplier_id, product_barcode, monkeypatch
    ):
        pid = _make_po(supplier_id, status='SENT')
        po_ctrl.add_po_line(pid, product_barcode, 'Test Product', 10, unit_cost=2.00)
        line = po_ctrl.get_po_lines(pid)[0]
        po_ctrl.receive_po_atomic(
            pid, po_ctrl.get_po_by_id(pid)['po_number'],
            [{'line_id': line['id'], 'barcode': product_barcode, 'new_received_qty': 3,
              'actual_cost': 2.00, 'unit_cost': 2.00, 'is_promo': False, 'qty_units': 3}],
            final_status='PARTIAL',
        )
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        _mock_qmessagebox(monkeypatch, question_return=QMessageBox.StandardButton.No)

        po_list_view._update_po()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'PARTIAL'


# ── _cancel_po guards ──────────────────────────────────────────────────────────

class TestCancelPo:
    def test_no_selection_shows_info(self, po_list_view, monkeypatch):
        po_list_view.active_table.clearSelection()
        po_list_view.active_table.setCurrentCell(-1, -1)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._cancel_po()
        mock_mb.information.assert_called_once()

    def test_received_po_cannot_be_cancelled(self, po_list_view, supplier_id, monkeypatch):
        """RECEIVED orders never actually appear in active_table (the loader
        excludes them), so this exercises the guard clause directly by
        injecting a RECEIVED row — defensive, but still real code that
        should never silently cancel a completed order."""
        pid = _make_po(supplier_id, status='RECEIVED')
        row = po_ctrl.get_po_with_supplier(pid)
        po_list_view._populate_table(po_list_view.active_table, [row])
        _select_row(po_list_view.active_table, pid)
        mock_mb = _mock_qmessagebox(monkeypatch)

        po_list_view._cancel_po()

        mock_mb.information.assert_called_once()
        assert po_ctrl.get_po_by_id(pid)['status'] == 'RECEIVED'

    def test_confirmed_cancel_sets_cancelled(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='SENT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        _mock_qmessagebox(monkeypatch, warning_return=QMessageBox.StandardButton.Yes)

        po_list_view._cancel_po()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'CANCELLED'

    def test_declined_cancel_leaves_status_unchanged(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='SENT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        _mock_qmessagebox(monkeypatch, warning_return=QMessageBox.StandardButton.No)

        po_list_view._cancel_po()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'SENT'


# ── _close_po ──────────────────────────────────────────────────────────────────

class TestClosePo:
    def test_no_selection_shows_info(self, po_list_view, monkeypatch):
        po_list_view.active_table.clearSelection()
        po_list_view.active_table.setCurrentCell(-1, -1)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._close_po()
        mock_mb.information.assert_called_once()

    def test_non_partial_po_blocked(self, po_list_view, supplier_id, monkeypatch):
        pid = _make_po(supplier_id, status='SENT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        mock_mb = _mock_qmessagebox(monkeypatch)
        po_list_view._close_po()
        mock_mb.warning.assert_called_once()

    def test_partial_with_all_lines_received_closes_immediately(
        self, po_list_view, supplier_id, product_barcode, monkeypatch
    ):
        """If a PO is PARTIAL but every line is actually fully received
        (edge case), _close_po short-circuits straight to RECEIVED with no
        extra dialog."""
        pid = _make_po(supplier_id, status='SENT')
        po_ctrl.add_po_line(pid, product_barcode, 'Test Product', 5, unit_cost=2.00)
        line = po_ctrl.get_po_lines(pid)[0]
        po_ctrl.receive_po_atomic(
            pid, po_ctrl.get_po_by_id(pid)['po_number'],
            [{'line_id': line['id'], 'barcode': product_barcode, 'new_received_qty': 5,
              'actual_cost': 2.00, 'unit_cost': 2.00, 'is_promo': False, 'qty_units': 5}],
            final_status='PARTIAL',
        )
        # Force status back to PARTIAL with nothing left unreceived, simulating
        # the edge case where get_unreceived_lines() finds none.
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)

        po_list_view._close_po()

        assert po_ctrl.get_po_by_id(pid)['status'] == 'RECEIVED'


# ── Update-PO button enablement ────────────────────────────────────────────────

class TestOnSelectionChanged:
    def test_button_disabled_for_non_partial(self, po_list_view, supplier_id):
        pid = _make_po(supplier_id, status='SENT')
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        assert not po_list_view.btn_update_po.isEnabled()

    def test_button_enabled_for_partial_with_received_lines(
        self, po_list_view, supplier_id, product_barcode
    ):
        pid = _make_po(supplier_id, status='SENT')
        po_ctrl.add_po_line(pid, product_barcode, 'Test Product', 5, unit_cost=2.00)
        line = po_ctrl.get_po_lines(pid)[0]
        po_ctrl.receive_po_atomic(
            pid, po_ctrl.get_po_by_id(pid)['po_number'],
            [{'line_id': line['id'], 'barcode': product_barcode, 'new_received_qty': 2,
              'actual_cost': 2.00, 'unit_cost': 2.00, 'is_promo': False, 'qty_units': 2}],
            final_status='PARTIAL',
        )
        po_list_view.load()
        _select_row(po_list_view.active_table, pid)
        assert po_list_view.btn_update_po.isEnabled()
