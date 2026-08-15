"""Widget regression tests for POReceive (views/purchase_orders/po_receive.py).

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt
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
def sent_po_multi_pack(db_conn, supplier_id, product_barcode):
    """SENT PO with one product line (2 cartons of 6, pack_qty=6).

    POReceive derives cartons math from the *product's* current pack_qty
    (matching po_detail.py / po_lines.py), not the po_line's own pack_qty
    column, so the product row must be updated too.
    """
    db_conn.execute("UPDATE products SET pack_qty=6 WHERE barcode=?", (product_barcode,))
    db_conn.commit()
    po_id = po_ctrl.create_po(supplier_id, delivery_date="2026-07-01")
    po_ctrl.update_po_status(po_id, "SENT")
    po_ctrl.add_po_line(po_id, product_barcode, "Test Product", 2, unit_cost=2.00, pack_qty=6)
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


def _stub_add_charge_dialog(monkeypatch, charge_type='OTHER', description='Charge',
                             tax_rate=0.0, amount_inc_tax=0.01):
    """Stand in for AddChargeDialog so _add_charge() doesn't block on a real
    modal — pretends the user picked the given type/description/tax/amount
    and clicked Add."""
    import views.purchase_orders.po_receive as _mod
    from PyQt6.QtWidgets import QDialog

    data = {
        'charge_type': charge_type,
        'description': description,
        'tax_rate': tax_rate,
        'amount_inc_tax': amount_inc_tax,
    }

    class _StubDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def data(self):
            return data

    monkeypatch.setattr(_mod, 'AddChargeDialog', _StubDialog)


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

    def test_partial_carton_qty_prompts_extra_confirmation(
        self, qtbot, monkeypatch, sent_po_multi_pack
    ):
        """Entering a qty that isn't a whole number of cartons (pack_qty=6,
        qty=5) must prompt an extra confirmation before receiving."""
        from views.purchase_orders.po_receive import POReceive
        w = POReceive(sent_po_multi_pack)
        qtbot.addWidget(w)
        mock_mb = _yes(monkeypatch)
        w.supplier_invoice_input.setText("INV-001")
        qty_input = w.table.cellWidget(0, 5)
        qty_input.setValue(5)  # pack_qty=6 — not a whole carton

        w._confirm()

        # One dialog for the partial-carton warning, one for the receipt confirm
        assert mock_mb.question.call_count == 2
        assert po_ctrl.get_po_by_id(sent_po_multi_pack)["status"] == "PARTIAL"

    def test_declining_partial_carton_warning_blocks_receipt(
        self, qtbot, monkeypatch, sent_po_multi_pack
    ):
        from views.purchase_orders.po_receive import POReceive
        w = POReceive(sent_po_multi_pack)
        qtbot.addWidget(w)
        _no(monkeypatch)
        w.supplier_invoice_input.setText("INV-001")
        qty_input = w.table.cellWidget(0, 5)
        qty_input.setValue(5)  # pack_qty=6 — not a whole carton

        w._confirm()

        assert po_ctrl.get_po_by_id(sent_po_multi_pack)["status"] == "SENT"

    def test_whole_carton_qty_skips_partial_carton_warning(
        self, qtbot, monkeypatch, sent_po_multi_pack
    ):
        from views.purchase_orders.po_receive import POReceive
        w = POReceive(sent_po_multi_pack)
        qtbot.addWidget(w)
        mock_mb = _yes(monkeypatch)
        w.supplier_invoice_input.setText("INV-001")
        qty_input = w.table.cellWidget(0, 5)
        qty_input.setValue(6)  # exactly one carton

        w._confirm()

        # Only the ordinary receipt-confirm dialog, no partial-carton warning
        assert mock_mb.question.call_count == 1

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


# ── Over-receiving ───────────────────────────────────────────────────────────

class TestOverReceive:
    def test_qty_input_accepts_more_than_ordered(self, po_receive_view):
        """Ordered 5 — spinner must no longer cap at the remaining quantity."""
        qty_input = po_receive_view.table.cellWidget(0, 5)
        qty_input.setValue(7)
        assert qty_input.value() == 7

    def test_over_receive_highlights_qty_input(self, po_receive_view):
        import config.styles as styles
        qty_input = po_receive_view.table.cellWidget(0, 5)
        qty_input.setValue(7)  # ordered 5
        assert styles.CLR_WARNING in qty_input.styleSheet()

        qty_input.setValue(5)  # back within the ordered amount
        assert qty_input.styleSheet() == ""

    def test_over_receive_prompts_warning_and_confirming_receives_full_qty(
        self, po_receive_view, monkeypatch, sent_po, product_barcode
    ):
        import models.stock_on_hand as soh_model
        mock_mb = _yes(monkeypatch)
        mock_mb.warning.return_value = QMessageBox.StandardButton.Yes
        po_receive_view.supplier_invoice_input.setText("INV-001")
        qty_input = po_receive_view.table.cellWidget(0, 5)
        qty_input.setValue(7)  # ordered 5

        po_receive_view._confirm()

        mock_mb.warning.assert_called_once()
        assert po_ctrl.get_po_by_id(sent_po)["status"] == "RECEIVED"
        soh = soh_model.get_by_barcode(product_barcode)
        assert soh["quantity"] == 7

    def test_declining_over_receive_warning_blocks_receipt(
        self, po_receive_view, monkeypatch, sent_po
    ):
        mock_mb = _yes(monkeypatch)
        mock_mb.warning.return_value = QMessageBox.StandardButton.No
        po_receive_view.supplier_invoice_input.setText("INV-001")
        qty_input = po_receive_view.table.cellWidget(0, 5)
        qty_input.setValue(7)  # ordered 5

        po_receive_view._confirm()

        mock_mb.warning.assert_called_once()
        assert po_ctrl.get_po_by_id(sent_po)["status"] == "SENT"

    def test_exact_qty_skips_over_receive_warning(self, po_receive_view, monkeypatch, sent_po):
        mock_mb = _yes(monkeypatch)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()  # fills exactly the remaining amount

        po_receive_view._confirm()

        mock_mb.warning.assert_not_called()
        assert po_ctrl.get_po_by_id(sent_po)["status"] == "RECEIVED"


# ── Additional Charges ────────────────────────────────────────────────────────

class TestCharges:
    def test_valid_amount_stored_as_canonical_float(self, po_receive_view, monkeypatch):
        _stub_add_charge_dialog(monkeypatch, charge_type='FREIGHT', description='Freight')
        po_receive_view._add_charge()
        amt_item = po_receive_view.charges_table.item(0, 3)
        amt_item.setText("15.00")

        po_receive_view._on_charge_item_changed(amt_item)

        assert amt_item.data(Qt.ItemDataRole.UserRole) == 15.00
        assert "15.00" in po_receive_view.total_label.text()

    def test_invalid_amount_flagged_and_excluded_from_total(self, po_receive_view, monkeypatch):
        _stub_add_charge_dialog(monkeypatch, charge_type='FREIGHT', description='Freight')
        po_receive_view._add_charge()
        amt_item = po_receive_view.charges_table.item(0, 3)
        amt_item.setText("not a number")

        po_receive_view._on_charge_item_changed(amt_item)

        assert amt_item.data(Qt.ItemDataRole.UserRole) is None

    def test_invalid_amount_blocks_confirm(self, po_receive_view, monkeypatch, sent_po):
        mock_mb = _yes(monkeypatch)
        _stub_add_charge_dialog(monkeypatch, charge_type='FREIGHT', description='Freight')
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()
        po_receive_view._add_charge()
        amt_item = po_receive_view.charges_table.item(0, 3)
        amt_item.setText("abc")
        po_receive_view._on_charge_item_changed(amt_item)

        po_receive_view._confirm()

        mock_mb.warning.assert_called_once()
        assert po_ctrl.get_po_by_id(sent_po)["status"] == "SENT"

    def test_negative_amount_rejected_for_non_rounding_charge(self, po_receive_view, monkeypatch):
        _stub_add_charge_dialog(monkeypatch, charge_type='FREIGHT', description='Freight')
        po_receive_view._add_charge()
        amt_item = po_receive_view.charges_table.item(0, 3)
        amt_item.setText("-5.00")

        po_receive_view._on_charge_item_changed(amt_item)

        assert amt_item.data(Qt.ItemDataRole.UserRole) is None

    def test_negative_amount_allowed_for_rounding_charge(self, po_receive_view, monkeypatch):
        _stub_add_charge_dialog(monkeypatch, charge_type='ROUNDING', description='Rounding')
        po_receive_view._add_charge()
        amt_item = po_receive_view.charges_table.item(0, 3)
        amt_item.setText("-0.05")

        po_receive_view._on_charge_item_changed(amt_item)

        assert amt_item.data(Qt.ItemDataRole.UserRole) == pytest.approx(-0.05)
        assert amt_item.data(Qt.ItemDataRole.UserRole) is not None

    def test_charge_type_carried_through_to_confirm(self, po_receive_view, monkeypatch, sent_po):
        _yes(monkeypatch)
        _stub_add_charge_dialog(monkeypatch, charge_type='FUEL_LEVY',
                                 description='Fuel Levy', tax_rate=10.0, amount_inc_tax=3.30)
        po_receive_view.supplier_invoice_input.setText("INV-001")
        po_receive_view._receive_all()
        po_receive_view._add_charge()

        po_receive_view._confirm()

        stored = po_ctrl.get_po_charges(sent_po)
        assert len(stored) == 1
        assert stored[0]["charge_type"] == "FUEL_LEVY"
        assert stored[0]["description"] == "Fuel Levy"
