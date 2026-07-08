"""Widget regression tests for StocktakeSession (views/stocktake/stocktake_session.py).

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.stocktake_controller as stocktake_ctrl


@pytest.fixture()
def session_id(test_db):
    return stocktake_ctrl.create_session("Test Session")


@pytest.fixture()
def stocktake_view(qtbot, session_id):
    from views.stocktake.stocktake_session import StocktakeSession
    widget = StocktakeSession(session_id)
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _mock_qmessagebox(monkeypatch, question_returns=None):
    import views.stocktake.stocktake_session as _mod
    mock_mb = MagicMock(spec=QMessageBox)
    mock_mb.StandardButton = QMessageBox.StandardButton
    if question_returns is not None:
        mock_mb.question.side_effect = question_returns
    monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)
    return mock_mb


# ── Loading ───────────────────────────────────────────────────────────────────

class TestLoad:
    def test_header_shows_label_and_open_status(self, stocktake_view):
        assert "Test Session" in stocktake_view.header.text()
        assert "OPEN" in stocktake_view.header.text()

    def test_scan_input_enabled_when_open(self, stocktake_view):
        assert stocktake_view.scan_input.isEnabled()

    def test_scan_input_disabled_when_closed(self, qtbot, db_conn, session_id):
        db_conn.execute("UPDATE stocktake_sessions SET status='CLOSED' WHERE id=?", (session_id,))
        db_conn.commit()
        from views.stocktake.stocktake_session import StocktakeSession
        w = StocktakeSession(session_id)
        qtbot.addWidget(w)
        assert not w.scan_input.isEnabled()

    def test_empty_session_has_no_rows(self, stocktake_view):
        assert stocktake_view.table.rowCount() == 0


# ── _on_scan ──────────────────────────────────────────────────────────────────

class TestOnScan:
    def test_unknown_barcode_shows_warning_and_adds_no_row(self, stocktake_view):
        stocktake_view.scan_input.setText("0000000000000")
        stocktake_view._on_scan()
        assert "not found" in stocktake_view.scan_status.text().lower()
        assert stocktake_view.table.rowCount() == 0

    def test_known_barcode_adds_row(self, stocktake_view, product_barcode):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view.qty_input.setValue(5)
        stocktake_view._on_scan()
        assert stocktake_view.table.rowCount() == 1
        assert stocktake_view.table.item(0, 0).text() == product_barcode
        assert stocktake_view.table.item(0, 4).text() == "5"

    def test_scan_clears_input_and_resets_qty(self, stocktake_view, product_barcode):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view.qty_input.setValue(5)
        stocktake_view._on_scan()
        assert stocktake_view.scan_input.text() == ""
        assert stocktake_view.qty_input.value() == 1

    def test_rescanning_same_barcode_accumulates_qty(self, stocktake_view, product_barcode):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view.qty_input.setValue(3)
        stocktake_view._on_scan()
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view.qty_input.setValue(2)
        stocktake_view._on_scan()
        assert stocktake_view.table.rowCount() == 1
        assert stocktake_view.table.item(0, 4).text() == "5"

    def test_blank_barcode_is_ignored(self, stocktake_view):
        stocktake_view.scan_input.setText("   ")
        stocktake_view._on_scan()
        assert stocktake_view.table.rowCount() == 0


# ── _remove_line ──────────────────────────────────────────────────────────────

class TestRemoveLine:
    def test_no_selection_shows_info_and_removes_nothing(self, stocktake_view, monkeypatch, product_barcode):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view._on_scan()
        mock_mb = _mock_qmessagebox(monkeypatch)
        stocktake_view.table.clearSelection()
        stocktake_view.table.setCurrentCell(-1, -1)

        stocktake_view._remove_line()

        mock_mb.information.assert_called_once()
        assert stocktake_view.table.rowCount() == 1

    def test_confirmed_removal_deletes_row(self, stocktake_view, monkeypatch, product_barcode):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view._on_scan()
        _mock_qmessagebox(monkeypatch, question_returns=[QMessageBox.StandardButton.Yes])
        stocktake_view.table.selectRow(0)

        stocktake_view._remove_line()

        assert stocktake_view.table.rowCount() == 0

    def test_declined_removal_keeps_row(self, stocktake_view, monkeypatch, product_barcode):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view._on_scan()
        _mock_qmessagebox(monkeypatch, question_returns=[QMessageBox.StandardButton.No])
        stocktake_view.table.selectRow(0)

        stocktake_view._remove_line()

        assert stocktake_view.table.rowCount() == 1


# ── _apply_session / _do_apply ─────────────────────────────────────────────────

class TestApplySession:
    def test_empty_session_shows_warning(self, stocktake_view, monkeypatch):
        mock_mb = _mock_qmessagebox(monkeypatch)
        stocktake_view._apply_session()
        mock_mb.warning.assert_called_once()

    def test_already_closed_session_shows_info(self, stocktake_view, monkeypatch, db_conn, session_id):
        db_conn.execute("UPDATE stocktake_sessions SET status='CLOSED' WHERE id=?", (session_id,))
        db_conn.commit()
        stocktake_view.load()  # refresh self._session to reflect the CLOSED status
        mock_mb = _mock_qmessagebox(monkeypatch)

        stocktake_view._apply_session()

        mock_mb.information.assert_called_once()

    def test_choosing_review_opens_variance_report_not_apply(
        self, stocktake_view, monkeypatch, product_barcode
    ):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view._on_scan()
        _mock_qmessagebox(monkeypatch, question_returns=[QMessageBox.StandardButton.Yes])
        with patch.object(stocktake_view, '_open_variance_report') as mock_open, \
             patch.object(stocktake_view, '_do_apply') as mock_apply:
            stocktake_view._apply_session()
            mock_open.assert_called_once()
            mock_apply.assert_not_called()

    def test_skip_review_and_confirm_applies_and_closes_session(
        self, stocktake_view, monkeypatch, product_barcode, session_id
    ):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view.qty_input.setValue(7)
        stocktake_view._on_scan()
        _mock_qmessagebox(monkeypatch, question_returns=[
            QMessageBox.StandardButton.No,   # skip variance review
            QMessageBox.StandardButton.Yes,  # confirm apply
        ])

        stocktake_view._apply_session()

        assert stocktake_ctrl.get_session(session_id)['status'] == 'CLOSED'

    def test_apply_calls_on_close_callback(self, qtbot, monkeypatch, session_id, product_barcode):
        from views.stocktake.stocktake_session import StocktakeSession
        on_close = MagicMock()
        w = StocktakeSession(session_id, on_close=on_close)
        qtbot.addWidget(w)
        w.scan_input.setText(product_barcode)
        w._on_scan()
        _mock_qmessagebox(monkeypatch, question_returns=[
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ])

        w._apply_session()

        on_close.assert_called_once()

    def test_apply_failure_shows_error_not_crash(
        self, stocktake_view, monkeypatch, product_barcode
    ):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view._on_scan()
        _mock_qmessagebox(monkeypatch, question_returns=[
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ])
        monkeypatch.setattr(
            stocktake_ctrl, "apply_session",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db exploded")),
        )

        with patch('views.stocktake.stocktake_session.show_error') as mock_show_error:
            stocktake_view._apply_session()  # must not raise
            mock_show_error.assert_called_once()

    def test_declining_confirm_leaves_session_open(
        self, stocktake_view, monkeypatch, product_barcode, session_id
    ):
        stocktake_view.scan_input.setText(product_barcode)
        stocktake_view._on_scan()
        _mock_qmessagebox(monkeypatch, question_returns=[
            QMessageBox.StandardButton.No,  # skip review
            QMessageBox.StandardButton.No,  # decline apply
        ])

        stocktake_view._apply_session()

        assert stocktake_ctrl.get_session(session_id)['status'] == 'OPEN'
