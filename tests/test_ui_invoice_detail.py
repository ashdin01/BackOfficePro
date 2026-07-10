"""Widget regression tests for invoice_detail.py's new-invoice customer picker.

Covers the fix for: the Customer field on "New Invoice" used to be a
QComboBox with no default-blocking placeholder, so clicking OK without
touching it created an invoice against whichever customer sorted first —
a real billing-against-the-wrong-customer risk. Customer must now be
actively picked via a search dialog before OK is even clickable.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import patch
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QPushButton

import controllers.ar_controller as ar_ctrl


@pytest.fixture()
def two_customers(db_conn):
    """Deliberately named so alphabetical-first != the one a test picks."""
    db_conn.execute(
        "INSERT INTO customers (code, name, payment_terms_days) VALUES ('AAA', 'AAA Customer', 30)"
    )
    db_conn.execute(
        "INSERT INTO customers (code, name, payment_terms_days) VALUES ('ZZZ', 'ZZZ Customer', 30)"
    )
    db_conn.commit()
    aaa_id = db_conn.execute("SELECT id FROM customers WHERE code='AAA'").fetchone()["id"]
    zzz_id = db_conn.execute("SELECT id FROM customers WHERE code='ZZZ'").fetchone()["id"]
    return {"aaa_id": aaa_id, "zzz_id": zzz_id}


# ── _CustomerLookup in isolation ────────────────────────────────────────────────

class TestCustomerLookup:
    def test_search_filters_by_name_or_code(self, qtbot, test_db, two_customers):
        from views.ar.invoice_detail import _CustomerLookup
        dlg = _CustomerLookup()
        qtbot.addWidget(dlg)

        dlg.search.setText("ZZZ")
        dlg._filter()

        names = [dlg.table.item(r, 1).text() for r in range(dlg.table.rowCount())]
        assert names == ["ZZZ Customer"]

    def test_picking_a_row_sets_selected_id_and_name(self, qtbot, test_db, two_customers):
        from views.ar.invoice_detail import _CustomerLookup
        dlg = _CustomerLookup()
        qtbot.addWidget(dlg)

        row = next(r for r in range(dlg.table.rowCount())
                   if dlg.table.item(r, 0).text() == 'ZZZ')
        dlg.table.selectRow(row)
        dlg._pick()

        assert dlg.selected_id == two_customers['zzz_id']
        assert dlg.selected_name == 'ZZZ Customer'

    def test_no_selection_by_default(self, qtbot, test_db, two_customers):
        from views.ar.invoice_detail import _CustomerLookup
        dlg = _CustomerLookup()
        qtbot.addWidget(dlg)
        assert dlg.selected_id is None


# ── Full new-invoice flow ────────────────────────────────────────────────────────

def _find_button(dialog, text):
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


class TestNewInvoiceDialogFlow:
    def test_ok_disabled_until_customer_picked_then_creates_for_the_picked_one(
        self, qtbot, test_db, two_customers, monkeypatch
    ):
        """End-to-end: OK starts disabled; picking ZZZ (not AAA, which sorts
        first) via the lookup enables it; the created invoice belongs to ZZZ."""
        from views.ar.invoice_detail import InvoiceDetail, _CustomerLookup

        def fake_exec(dialog_self):
            if isinstance(dialog_self, _CustomerLookup):
                row = next(r for r in range(dialog_self.table.rowCount())
                           if dialog_self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
                           == two_customers['zzz_id'])
                dialog_self.table.selectRow(row)
                dialog_self._pick()
                return QDialog.DialogCode.Accepted
            else:
                # The "New Invoice" dialog itself.
                select_btn = _find_button(dialog_self, "Select…")
                select_btn.click()  # synchronously opens & resolves _CustomerLookup above

                ok_btn = dialog_self.findChild(QDialogButtonBox).button(
                    QDialogButtonBox.StandardButton.Ok
                )
                assert ok_btn.isEnabled(), "OK should be enabled once a customer is picked"
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)

        detail = InvoiceDetail(invoice_id=None)
        qtbot.addWidget(detail)

        invoices = ar_ctrl.get_all_invoices(customer_id=two_customers['zzz_id'])
        assert len(invoices) == 1
        aaa_invoices = ar_ctrl.get_all_invoices(customer_id=two_customers['aaa_id'])
        assert aaa_invoices == []

    def test_cancelling_customer_picker_leaves_ok_disabled(
        self, qtbot, test_db, two_customers, monkeypatch
    ):
        from views.ar.invoice_detail import InvoiceDetail, _CustomerLookup

        def fake_exec(dialog_self):
            if isinstance(dialog_self, _CustomerLookup):
                return QDialog.DialogCode.Rejected  # user cancelled the picker
            else:
                select_btn = _find_button(dialog_self, "Select…")
                select_btn.click()
                ok_btn = dialog_self.findChild(QDialogButtonBox).button(
                    QDialogButtonBox.StandardButton.Ok
                )
                assert not ok_btn.isEnabled()
                return QDialog.DialogCode.Rejected  # user then cancels the whole dialog

        monkeypatch.setattr(QDialog, "exec", fake_exec)

        detail = InvoiceDetail(invoice_id=None)
        qtbot.addWidget(detail)

        assert ar_ctrl.get_all_invoices() == []


# ── Loaded (existing) invoice — lines, payments, status, notes ──────────────────

@pytest.fixture()
def draft_invoice_id(test_db, customer_id):
    inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-01")
    return inv_id


@pytest.fixture()
def invoice_detail_view(qtbot, draft_invoice_id):
    from views.ar.invoice_detail import InvoiceDetail
    widget = InvoiceDetail(invoice_id=draft_invoice_id)
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _fake_line_dialog(monkeypatch, description="Widget", qty=2, unit_price=10.00, gst_rate=10.0):
    from views.ar.invoice_detail import _LineDialog

    def fake_exec(dlg_self):
        dlg_self.description.setText(description)
        dlg_self.qty.setValue(qty)
        dlg_self.unit_price.setValue(unit_price)
        dlg_self.gst_rate.setValue(gst_rate)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(_LineDialog, "exec", fake_exec)


class TestLoadedInvoice:
    def test_load_populates_header(self, invoice_detail_view, customer_id):
        import controllers.ar_controller as _ar
        customer = _ar.get_customer_by_id(customer_id)
        assert customer['name'] in invoice_detail_view.lbl_customer.text()

    def test_new_draft_invoice_has_no_lines(self, invoice_detail_view):
        assert invoice_detail_view.table.rowCount() == 0

    def test_draft_status_allows_adding_lines(self, invoice_detail_view):
        assert invoice_detail_view.btn_add_line.isEnabled()


class TestAddEditDeleteLine:
    def test_add_line_appends_row_and_updates_totals(
        self, invoice_detail_view, monkeypatch
    ):
        _fake_line_dialog(monkeypatch, description="Widget", qty=2, unit_price=10.00, gst_rate=10.0)

        invoice_detail_view._add_line()

        assert invoice_detail_view.table.rowCount() == 1
        assert invoice_detail_view.table.item(0, 0).text() == "Widget"
        # 2 x $10 = $20 ex GST, GST 10% = $2, total $22
        assert "$22.00" in invoice_detail_view.lbl_total.text()

    def test_edit_line_updates_existing_row_not_a_new_one(
        self, invoice_detail_view, monkeypatch
    ):
        _fake_line_dialog(monkeypatch, description="Widget", qty=1, unit_price=5.00)
        invoice_detail_view._add_line()
        assert invoice_detail_view.table.rowCount() == 1

        invoice_detail_view.table.selectRow(0)
        _fake_line_dialog(monkeypatch, description="Widget (Updated)", qty=1, unit_price=5.00)
        invoice_detail_view._edit_line()

        assert invoice_detail_view.table.rowCount() == 1
        assert invoice_detail_view.table.item(0, 0).text() == "Widget (Updated)"

    def test_delete_line_removes_row_after_confirmation(
        self, invoice_detail_view, monkeypatch
    ):
        _fake_line_dialog(monkeypatch)
        invoice_detail_view._add_line()
        assert invoice_detail_view.table.rowCount() == 1

        import views.ar.invoice_detail as _mod
        monkeypatch.setattr(
            _mod.QMessageBox, "question",
            lambda *a, **kw: _mod.QMessageBox.StandardButton.Yes
        )
        invoice_detail_view.table.selectRow(0)
        invoice_detail_view._delete_line()

        assert invoice_detail_view.table.rowCount() == 0

    def test_delete_line_declined_keeps_row(self, invoice_detail_view, monkeypatch):
        _fake_line_dialog(monkeypatch)
        invoice_detail_view._add_line()

        import views.ar.invoice_detail as _mod
        monkeypatch.setattr(
            _mod.QMessageBox, "question",
            lambda *a, **kw: _mod.QMessageBox.StandardButton.No
        )
        invoice_detail_view.table.selectRow(0)
        invoice_detail_view._delete_line()

        assert invoice_detail_view.table.rowCount() == 1

    def test_blank_description_blocked_by_line_dialog_itself(self, qtbot, test_db):
        from views.ar.invoice_detail import _LineDialog
        dlg = _LineDialog()
        qtbot.addWidget(dlg)
        dlg.description.setText("   ")

        with patch('views.ar.invoice_detail.QMessageBox') as mock_mb:
            dlg._accept()
            mock_mb.warning.assert_called_once()
        assert dlg.result() != QDialog.DialogCode.Accepted


class TestStatusChange:
    def test_status_changed_persists_and_reloads(self, invoice_detail_view, draft_invoice_id):
        invoice_detail_view._status_changed("SENT")
        assert ar_ctrl.get_invoice_by_id(draft_invoice_id)['status'] == "SENT"

    def test_sent_status_disables_add_line(self, invoice_detail_view, draft_invoice_id):
        invoice_detail_view._status_changed("SENT")
        assert not invoice_detail_view.btn_add_line.isEnabled()


class TestSaveNotes:
    def test_notes_persist(self, invoice_detail_view, draft_invoice_id):
        invoice_detail_view.notes_edit.setText("Deliver to back door")
        invoice_detail_view._save_notes()
        assert ar_ctrl.get_invoice_by_id(draft_invoice_id)['notes'] == "Deliver to back door"


class TestRecordPayment:
    def test_payment_updates_balance_and_status(
        self, invoice_detail_view, draft_invoice_id, monkeypatch
    ):
        _fake_line_dialog(monkeypatch, description="Widget", qty=1, unit_price=100.00, gst_rate=0.0)
        invoice_detail_view._add_line()
        invoice_detail_view._status_changed("SENT")

        from views.ar.payment_dialog import PaymentDialog

        def fake_exec(dlg_self):
            dlg_self.amount.setValue(100.00)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(PaymentDialog, "exec", fake_exec)

        invoice_detail_view._record_payment()

        inv = ar_ctrl.get_invoice_by_id(draft_invoice_id)
        assert inv['status'] == 'PAID'
        assert float(inv['amount_paid']) == pytest.approx(100.00)

    def test_partial_payment_leaves_balance_owing(
        self, invoice_detail_view, draft_invoice_id, monkeypatch
    ):
        _fake_line_dialog(monkeypatch, description="Widget", qty=1, unit_price=100.00, gst_rate=0.0)
        invoice_detail_view._add_line()
        invoice_detail_view._status_changed("SENT")

        from views.ar.payment_dialog import PaymentDialog

        def fake_exec(dlg_self):
            dlg_self.amount.setValue(40.00)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(PaymentDialog, "exec", fake_exec)

        invoice_detail_view._record_payment()

        assert "$60.00" in invoice_detail_view.lbl_owing.text()

    def test_cancelling_payment_dialog_makes_no_changes(
        self, invoice_detail_view, draft_invoice_id, monkeypatch
    ):
        from views.ar.payment_dialog import PaymentDialog
        monkeypatch.setattr(PaymentDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

        invoice_detail_view._record_payment()

        inv = ar_ctrl.get_invoice_by_id(draft_invoice_id)
        assert float(inv['amount_paid']) == 0.0


class TestExportPdfErrorHandling:
    def test_pdf_failure_shows_error_not_crash(self, invoice_detail_view, monkeypatch):
        import controllers.ar_controller as _ar_ctrl
        monkeypatch.setattr(
            _ar_ctrl, "generate_invoice_pdf",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk full")),
        )
        with patch('views.ar.invoice_detail.show_error') as mock_show_error:
            invoice_detail_view._export_pdf()  # must not raise
            mock_show_error.assert_called_once()
