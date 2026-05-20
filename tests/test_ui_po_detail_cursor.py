"""
Widget tests for PODetail cursor retention after line actions.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
Tests confirm that after delete / add-note / add-line the table selection
stays at the expected row rather than jumping to the top.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import models.purchase_order as po_model
import models.po_lines as lines_model


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def po_with_lines(test_db, db_conn, supplier_id, dept_id):
    """PO pre-loaded with 4 product lines. Returns po_id."""
    barcodes = ['1111111111111', '2222222222222', '3333333333333', '4444444444444']
    for i, bc in enumerate(barcodes):
        db_conn.execute("""
            INSERT INTO products
                (barcode, description, department_id, supplier_id,
                 sell_price, cost_price, tax_rate, pack_qty, pack_unit,
                 active, unit)
            VALUES (?, ?, ?, ?, 3.50, 2.00, 10.0, 6, 'EA', 1, 'EA')
        """, (bc, f'Product {i + 1}', dept_id, supplier_id))
    db_conn.commit()

    po_id = po_model.create(supplier_id, '2026-06-01', '', 'admin')
    for i, bc in enumerate(barcodes):
        lines_model.add(po_id, bc, f'Product {i + 1}', 1, 2.00)
    return po_id


@pytest.fixture()
def po_detail(qtbot, po_with_lines):
    """Live PODetail widget with the 4-line PO."""
    from views.purchase_orders.po_detail import PODetail
    widget = PODetail(po_with_lines, blank=True)
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _yes(monkeypatch):
    """Patch QMessageBox.question (module-level import) to always return Yes."""
    import views.purchase_orders.po_detail as _mod
    mock_mb = MagicMock(spec=QMessageBox)
    mock_mb.question.return_value = QMessageBox.StandardButton.Yes
    mock_mb.StandardButton = QMessageBox.StandardButton
    mock_mb.Icon = QMessageBox.Icon
    monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)


def _no(monkeypatch):
    """Patch QMessageBox.question to always return No."""
    import views.purchase_orders.po_detail as _mod
    mock_mb = MagicMock(spec=QMessageBox)
    mock_mb.question.return_value = QMessageBox.StandardButton.No
    mock_mb.StandardButton = QMessageBox.StandardButton
    mock_mb.Icon = QMessageBox.Icon
    monkeypatch.setattr(_mod, 'QMessageBox', mock_mb)


# ── _remove_line cursor tests ─────────────────────────────────────────────────

class TestRemoveLineCursor:
    def test_remove_middle_row_cursor_stays_at_same_index(self, po_detail, monkeypatch):
        w = po_detail
        assert w.table.rowCount() == 4
        w.table.selectRow(2)
        _yes(monkeypatch)

        w._remove_line()
        QApplication.processEvents()

        assert w.table.rowCount() == 3
        assert w.table.currentRow() == 2

    def test_remove_first_row_cursor_stays_at_zero(self, po_detail, monkeypatch):
        w = po_detail
        w.table.selectRow(0)
        _yes(monkeypatch)

        w._remove_line()
        QApplication.processEvents()

        assert w.table.rowCount() == 3
        assert w.table.currentRow() == 0

    def test_remove_last_row_cursor_clamps_to_new_last(self, po_detail, monkeypatch):
        w = po_detail
        w.table.selectRow(3)
        _yes(monkeypatch)

        w._remove_line()
        QApplication.processEvents()

        assert w.table.rowCount() == 3
        assert w.table.currentRow() == 2

    def test_remove_cancelled_no_row_change(self, po_detail, monkeypatch):
        w = po_detail
        w.table.selectRow(2)
        _no(monkeypatch)

        w._remove_line()
        QApplication.processEvents()

        assert w.table.rowCount() == 4
        assert w.table.currentRow() == 2

    def test_remove_second_to_last_row_cursor_at_same_index(self, po_detail, monkeypatch):
        w = po_detail
        w.table.selectRow(2)   # second-to-last in a 4-row table
        _yes(monkeypatch)

        w._remove_line()
        QApplication.processEvents()

        # Row 3 (was last) shifts up to row 2 — cursor stays at 2
        assert w.table.rowCount() == 3
        assert w.table.currentRow() == 2


# ── _add_note cursor tests ────────────────────────────────────────────────────

class TestAddNoteCursor:
    def _mock_input(self, text, ok):
        """Return a context manager that patches QInputDialog.getText."""
        mock_cls = MagicMock()
        mock_cls.getText.return_value = (text, ok)
        return patch('PyQt6.QtWidgets.QInputDialog', mock_cls)

    def test_note_inserted_after_selected_row(self, po_detail):
        w = po_detail
        w.table.selectRow(1)

        with self._mock_input('Handle with care', True):
            w._add_note()
        QApplication.processEvents()

        # Note sits at row 2 (after the selected row 1)
        assert w.table.rowCount() == 5
        assert w.table.currentRow() == 2

    def test_note_at_first_row_cursor_moves_to_one(self, po_detail):
        w = po_detail
        w.table.selectRow(0)

        with self._mock_input('Top note', True):
            w._add_note()
        QApplication.processEvents()

        assert w.table.rowCount() == 5
        assert w.table.currentRow() == 1

    def test_note_at_last_row_cursor_moves_to_new_last(self, po_detail):
        w = po_detail
        w.table.selectRow(3)

        with self._mock_input('End note', True):
            w._add_note()
        QApplication.processEvents()

        assert w.table.rowCount() == 5
        assert w.table.currentRow() == 4

    def test_note_cancelled_no_change(self, po_detail):
        w = po_detail
        w.table.selectRow(2)

        with self._mock_input('', False):
            w._add_note()
        QApplication.processEvents()

        assert w.table.rowCount() == 4
        assert w.table.currentRow() == 2


# ── _add_line cursor tests ────────────────────────────────────────────────────

class TestAddLineCursor:
    def _mock_dialog(self, po_detail, db_conn, dept_id, supplier_id, accept=True):
        """
        If accept=True, pre-inserts a product+line so the reload sees a new row,
        then returns a mock AddLineDialog that accepts without running its own logic.
        """
        if accept:
            bc = '5555555555555'
            db_conn.execute("""
                INSERT OR IGNORE INTO products
                    (barcode, description, department_id, supplier_id,
                     sell_price, cost_price, tax_rate, pack_qty, pack_unit,
                     active, unit)
                VALUES (?, 'Product 5', ?, ?, 3.50, 2.00, 10.0, 6, 'EA', 1, 'EA')
            """, (bc, dept_id, supplier_id))
            db_conn.commit()
            lines_model.add(po_detail.po_id, bc, 'Product 5', 1, 2.00)

        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = accept
        return patch('views.purchase_orders.po_detail.AddLineDialog', return_value=mock_dlg)

    def test_add_line_cursor_moves_to_last_row(self, po_detail, db_conn, dept_id, supplier_id):
        w = po_detail
        w.table.selectRow(0)

        with self._mock_dialog(po_detail, db_conn, dept_id, supplier_id, accept=True):
            w._add_line()
        QApplication.processEvents()

        assert w.table.rowCount() == 5
        assert w.table.currentRow() == 4

    def test_add_line_cancelled_cursor_unchanged(self, po_detail, db_conn, dept_id, supplier_id):
        w = po_detail
        w.table.selectRow(2)

        with self._mock_dialog(po_detail, db_conn, dept_id, supplier_id, accept=False):
            w._add_line()
        QApplication.processEvents()

        assert w.table.rowCount() == 4
        assert w.table.currentRow() == 2
