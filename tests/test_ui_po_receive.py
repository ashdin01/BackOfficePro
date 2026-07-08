"""Widget regression tests for POReceive (views/purchase_orders/po_receive.py).

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.purchase_order_controller as po_ctrl


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def sent_po(db_conn, supplier_id, product_barcode):
    """SENT PO with one product line (5 cartons, pack_qty=1)."""
    po_id = po_ctrl.create_po(supplier_id, delivery_date="2026-07-01")
    po_ctrl.update_po_status(po_id, "SENT")
    po_ctrl.add_po_line(po_id, product_barcode, "Test Product", 5, unit_cost=2.00)
    return po_id


@pytest.fixture()
def po_receive_view(qtbot, sent_po):
    """Live POReceive widget for sent_po."""
    from views.purchase_orders.po_receive import POReceive
    widget = POReceive(sent_po)
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _yes(monkeypatch):
    import views.purchase_orders.po_receive as _mod
    mock_mb = MagicMock(spec=QMessageBox)
    mock_mb.question.return_value = QMessageBox.StandardButton.Yes
    mock_mb.StandardButton = QMessageBox.StandardButton
    mock_mb.warning = MagicMock()
    monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)
    return mock_mb


def _no(monkeypatch):
    import views.purchase_orders.po_receive as _mod
    mock_mb = MagicMock(spec=QMessageBox)
    mock_mb.question.return_value = QMessageBox.StandardButton.No
    mock_mb.StandardButton = QMessageBox.StandardButton
    mock_mb.warning = MagicMock()
    monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)
    return mock_mb


# ── Loading ───────────────────────────────────────────────────────────────────

class TestLoad:
    def test_table_has_one_row_per_line(self, po_receive_view):
        assert po_receive_view.table.rowCount() == 1

    def test_barcode_cell_matches_line(self, po_receive_view, product_barcode):
        assert po_receive_view.table.item(0, 0).text() == product_barcode

    def test_existing_invoice_number_prefilled(self, qtbot, db_conn, supplier_id, product_barcode):
        po_id = po_ctrl.create_po(supplier_id, delivery_date="2026-07-01")
        po_ctrl.update_po_status(po_id, "SENT")
        po_ctrl.add_po_line(po_id, product_barcode, "Test Product", 5, unit_cost=2.00)
        db_conn.execute(
            "UPDATE purchase_orders SET supplier_invoice_number='INV-EXIST' WHERE id=?", (po_id,)
        )
        db_conn.commit()
        from views.purchase_orders.po_receive import POReceive
        w = POReceive(po_id)
        qtbot.addWidget(w)
        assert w.supplier_invoice_input.text() == "INV-EXIST"


# ── _receive_all ──────────────────────────────────────────────────────────────

class TestReceiveAll:
    def test_fills_qty_to_remaining_units(self, po_receive_view):
        qty_input = po_receive_view.table.cellWidget(0, 5)
        assert qty_input.value() == 0
        po_receive_view._receive_all()
        assert qty_input.value() == 5


# ── _confirm ──────────────────────────────────────────────────────────────────

class TestConfirm:
    def test_missing_invoice_number_blocks_and_warns(self, po_receive_view, monkeypatch, sent_po):
        mock_mb = _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("")

        po_receive_view._confirm()

        mock_mb.warning.assert_called_once()
        assert po_ctrl.get_po_by_id(sent_po)["status"] == "SENT"

    def test_declining_confirmation_makes_no_changes(self, po_receive_view, monkeypatch, sent_po):
        _no(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()

        po_receive_view._confirm()

        assert po_ctrl.get_po_by_id(sent_po)["status"] == "SENT"

    def test_full_receipt_sets_status_received(self, po_receive_view, monkeypatch, sent_po):
        _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()

        po_receive_view._confirm()

        assert po_ctrl.get_po_by_id(sent_po)["status"] == "RECEIVED"

    def test_partial_receipt_sets_status_partial(self, po_receive_view, monkeypatch, sent_po):
        _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        qty_input = po_receive_view.table.cellWidget(0, 5)
        qty_input.setValue(2)  # ordered 5, receive only 2

        po_receive_view._confirm()

        assert po_ctrl.get_po_by_id(sent_po)["status"] == "PARTIAL"

    def test_confirm_calls_on_save_callback(self, qtbot, monkeypatch, sent_po):
        from views.purchase_orders.po_receive import POReceive
        on_save = MagicMock()
        w = POReceive(sent_po, on_save=on_save)
        qtbot.addWidget(w)
        _yes(monkeypatch)
        w.supplier_invoice_input.setText("INV-001")
        w._receive_all()

        w._confirm()

        on_save.assert_called_once()

    def test_stores_supplier_invoice_number(self, po_receive_view, monkeypatch, sent_po):
        _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-999")
        po_receive_view._receive_all()

        po_receive_view._confirm()

        assert po_ctrl.get_po_by_id(sent_po)["supplier_invoice_number"] == "INV-999"

    def test_updates_stock_on_hand(self, po_receive_view, monkeypatch, product_barcode):
        import models.stock_on_hand as soh_model
        _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()

        po_receive_view._confirm()

        soh = soh_model.get_by_barcode(product_barcode)
        assert soh["quantity"] == 5

    def test_already_received_po_shows_warning_and_skips(
        self, po_receive_view, monkeypatch, sent_po, db_conn
    ):
        """Race condition: PO was received elsewhere between opening this
        screen and clicking Confirm — must not double-receive."""
        mock_mb = _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()
        db_conn.execute("UPDATE purchase_orders SET status='RECEIVED' WHERE id=?", (sent_po,))
        db_conn.commit()

        po_receive_view._confirm()

        mock_mb.warning.assert_called_once()

    def test_receive_failure_shows_error_not_crash(self, po_receive_view, monkeypatch, sent_po):
        _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()
        monkeypatch.setattr(
            po_ctrl, "receive_po_atomic",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db exploded")),
        )

        with patch("views.purchase_orders.po_receive.show_error") as mock_show_error:
            po_receive_view._confirm()
            mock_show_error.assert_called_once()

        # PO status unchanged since the atomic write raised
        assert po_ctrl.get_po_by_id(sent_po)["status"] == "SENT"
