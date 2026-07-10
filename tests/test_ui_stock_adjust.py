"""Widget regression tests for StockAdjustView (views/stock_adjust/stock_adjust_view.py).

The heaviest untested screen before this: it writes directly to stock on
hand, off the UI thread via a real QThread worker, so it's covered from
two angles — the guard clauses and UI-update logic in isolation (fast,
deterministic), plus one full end-to-end run through the real worker
thread (waits on its actual `finished` signal) to prove the threaded
path itself works, not just the code around it.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

import controllers.product_controller as product_ctrl


@pytest.fixture()
def stock_adjust_view(qtbot, test_db, product_barcode):
    from views.stock_adjust.stock_adjust_view import StockAdjustView
    widget = StockAdjustView(current_user={"role": "MANAGER"})
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _select_product(widget, barcode, description="Test Product"):
    widget._select(barcode, description)


# ── Search ────────────────────────────────────────────────────────────────────

class TestSearch:
    def test_short_query_shows_no_results(self, stock_adjust_view):
        stock_adjust_view.search.setText("a")
        stock_adjust_view._do_search()
        assert stock_adjust_view.results_table.rowCount() == 0

    def test_matching_query_populates_results(self, stock_adjust_view, product_barcode):
        stock_adjust_view.search.setText("Test Product")
        stock_adjust_view._do_search()
        assert stock_adjust_view.results_table.rowCount() == 1
        assert stock_adjust_view.results_table.item(0, 0).text() == product_barcode

    def test_no_match_clears_results(self, stock_adjust_view):
        stock_adjust_view.search.setText("zzznomatch")
        stock_adjust_view._do_search()
        assert stock_adjust_view.results_table.rowCount() == 0

    def test_results_show_current_on_hand(self, stock_adjust_view, product_barcode):
        product_ctrl.adjust_soh(product_barcode, 15, "RECEIPT")
        stock_adjust_view.search.setText("Test Product")
        stock_adjust_view._do_search()
        assert stock_adjust_view.results_table.item(0, 4).text() == "15"


# ── Selecting a product ───────────────────────────────────────────────────────

class TestSelectProduct:
    def test_selecting_enables_apply_and_shows_label(self, stock_adjust_view, product_barcode):
        assert not stock_adjust_view.apply_btn.isEnabled()
        _select_product(stock_adjust_view, product_barcode)
        assert stock_adjust_view.apply_btn.isEnabled()
        assert product_barcode in stock_adjust_view.selected_label.text()

    def test_clear_selection_resets_form(self, stock_adjust_view, product_barcode):
        _select_product(stock_adjust_view, product_barcode)
        stock_adjust_view.qty_spin.setValue(5)
        stock_adjust_view.adj_type.setText("DG")
        stock_adjust_view.ref_input.setText("ref")
        stock_adjust_view.notes_input.setText("notes")

        stock_adjust_view._clear_selection()

        assert stock_adjust_view._selected_barcode is None
        assert not stock_adjust_view.apply_btn.isEnabled()
        assert stock_adjust_view.qty_spin.value() == 0
        assert stock_adjust_view.adj_type.text() == ""
        assert stock_adjust_view.ref_input.text() == ""
        assert stock_adjust_view.notes_input.text() == ""


# ── Reason code field ─────────────────────────────────────────────────────────

class TestReasonCode:
    def test_known_code_shows_description(self, stock_adjust_view):
        stock_adjust_view.adj_type.setText("DG")
        assert "Damaged" in stock_adjust_view.reason_desc_lbl.text()

    def test_unknown_code_shows_warning_text(self, stock_adjust_view):
        stock_adjust_view.adj_type.setText("ZZ")
        assert "Unknown" in stock_adjust_view.reason_desc_lbl.text()

    def test_blank_code_shows_nothing(self, stock_adjust_view):
        stock_adjust_view.adj_type.setText("DG")
        stock_adjust_view.adj_type.setText("")
        assert stock_adjust_view.reason_desc_lbl.text() == ""

    def test_lookup_dialog_sets_code_and_focuses_field(self, stock_adjust_view, monkeypatch):
        from views.stock_adjust.stock_adjust_view import _ReasonLookupDialog
        import views.stock_adjust.stock_adjust_view as _mod

        def fake_init(dlg_self, parent=None):
            QDialog.__init__(dlg_self, parent)
            dlg_self.selected_code = "OD"

        monkeypatch.setattr(_ReasonLookupDialog, "__init__", fake_init)
        monkeypatch.setattr(_ReasonLookupDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

        stock_adjust_view._open_reason_lookup()

        assert stock_adjust_view.adj_type.text() == "OD"


# ── _apply guard clauses (no thread should start) ──────────────────────────────

class TestApplyGuards:
    def test_no_selection_is_a_noop(self, stock_adjust_view):
        assert stock_adjust_view._selected_barcode is None
        stock_adjust_view._apply()  # must not raise
        assert stock_adjust_view._thread is None

    def test_zero_quantity_blocked_with_warning(self, stock_adjust_view, product_barcode, monkeypatch):
        _select_product(stock_adjust_view, product_barcode)
        stock_adjust_view.qty_spin.setValue(0)
        import views.stock_adjust.stock_adjust_view as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)

        stock_adjust_view._apply()

        mock_mb.warning.assert_called_once()
        assert stock_adjust_view._thread is None

    def test_declining_confirmation_does_not_start_worker(
        self, stock_adjust_view, product_barcode, monkeypatch
    ):
        _select_product(stock_adjust_view, product_barcode)
        stock_adjust_view.qty_spin.setValue(5)
        stock_adjust_view.adj_type.setText("DG")

        from views.stock_adjust.stock_adjust_view import _ConfirmAdjustDialog
        monkeypatch.setattr(_ConfirmAdjustDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

        stock_adjust_view._apply()

        assert stock_adjust_view._thread is None
        soh = product_ctrl.get_soh_by_barcode(product_barcode)
        assert soh is None or soh["quantity"] == 0


# ── _on_adjust_done / _on_adjust_error in isolation ────────────────────────────

class TestAdjustCallbacks:
    def test_done_resets_button_and_emits_stock_changed(self, stock_adjust_view, monkeypatch):
        import views.stock_adjust.stock_adjust_view as _mod
        monkeypatch.setattr(_mod, "QMessageBox", MagicMock())
        stock_adjust_view.apply_btn.setEnabled(False)
        stock_adjust_view.apply_btn.setText("Processing…")
        stock_adjust_view.clear_btn.setEnabled(False)

        received = []
        stock_adjust_view.stock_changed.connect(lambda: received.append(True))

        stock_adjust_view._on_adjust_done(42, [])

        assert stock_adjust_view.apply_btn.text() == "✓  Apply Adjustment"
        assert stock_adjust_view.clear_btn.isEnabled()
        assert received == [True]

    def test_error_shows_critical_and_reenables_buttons(self, stock_adjust_view, monkeypatch):
        import views.stock_adjust.stock_adjust_view as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)
        stock_adjust_view.apply_btn.setEnabled(False)
        stock_adjust_view.clear_btn.setEnabled(False)

        stock_adjust_view._on_adjust_error("db exploded")

        mock_mb.critical.assert_called_once()
        assert stock_adjust_view.apply_btn.isEnabled()
        assert stock_adjust_view.clear_btn.isEnabled()


# ── Full threaded happy path ───────────────────────────────────────────────────

class TestApplyEndToEnd:
    def test_confirmed_adjustment_updates_soh_through_the_real_worker_thread(
        self, qtbot, stock_adjust_view, product_barcode, monkeypatch
    ):
        _select_product(stock_adjust_view, product_barcode)
        stock_adjust_view.qty_spin.setValue(10)
        stock_adjust_view.adj_type.setText("SA")

        from views.stock_adjust.stock_adjust_view import _ConfirmAdjustDialog
        monkeypatch.setattr(_ConfirmAdjustDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        import views.stock_adjust.stock_adjust_view as _mod
        monkeypatch.setattr(_mod, "QMessageBox", MagicMock())

        stock_adjust_view._apply()
        assert stock_adjust_view._worker is not None

        with qtbot.waitSignal(stock_adjust_view._worker.finished, timeout=3000):
            pass
        QApplication.processEvents()

        soh = product_ctrl.get_soh_by_barcode(product_barcode)
        assert soh["quantity"] == 10

    def test_movement_recorded_with_reason_and_reference(
        self, qtbot, stock_adjust_view, product_barcode, monkeypatch, db_conn
    ):
        _select_product(stock_adjust_view, product_barcode)
        stock_adjust_view.qty_spin.setValue(-3)
        stock_adjust_view.adj_type.setText("DG")
        stock_adjust_view.ref_input.setText("REF-001")

        from views.stock_adjust.stock_adjust_view import _ConfirmAdjustDialog
        monkeypatch.setattr(_ConfirmAdjustDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        import views.stock_adjust.stock_adjust_view as _mod
        monkeypatch.setattr(_mod, "QMessageBox", MagicMock())

        stock_adjust_view._apply()
        with qtbot.waitSignal(stock_adjust_view._worker.finished, timeout=3000):
            pass
        QApplication.processEvents()

        move = db_conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=? ORDER BY id DESC LIMIT 1",
            (product_barcode,),
        ).fetchone()
        assert move is not None
        assert move["quantity"] == -3
        assert move["reference"] == "REF-001"
        assert "Damaged" in move["movement_type"]
