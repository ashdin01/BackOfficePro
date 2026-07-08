"""Widget tests for utils/keyboard_mixin.py — Escape/Ctrl+S/Enter shortcuts.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
from unittest.mock import MagicMock

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QTableWidget, QWidget

from utils.keyboard_mixin import KeyboardMixin


class _KWidget(KeyboardMixin, QWidget):
    pass


def _find_shortcut(widget, key_sequence: str) -> QShortcut:
    """Locate the QShortcut setup_keyboard() registered for key_sequence.

    QShortcut activation depends on real window-manager focus, which is
    unreliable in headless/CI test environments — emitting .activated
    directly exercises the same connected callback deterministically.
    """
    target = QKeySequence(key_sequence)
    for sc in widget.findChildren(QShortcut):
        if sc.key() == target:
            return sc
    raise AssertionError(f"No QShortcut found for {key_sequence!r}")


class TestEscape:
    def test_default_escape_closes_widget(self, qtbot):
        w = _KWidget()
        qtbot.addWidget(w)
        w.setup_keyboard()
        w.show()
        QApplication.processEvents()
        assert w.isVisible()

        _find_shortcut(w, "Escape").activated.emit()
        QApplication.processEvents()

        assert not w.isVisible()

    def test_custom_on_escape_used_instead_of_close(self, qtbot):
        w = _KWidget()
        qtbot.addWidget(w)
        on_escape = MagicMock()
        w.setup_keyboard(on_escape=on_escape)
        w.show()
        QApplication.processEvents()

        _find_shortcut(w, "Escape").activated.emit()

        on_escape.assert_called_once()
        assert w.isVisible()


class TestCtrlS:
    def test_calls_save_when_present(self, qtbot):
        w = _KWidget()
        qtbot.addWidget(w)
        w._save = MagicMock()
        w.setup_keyboard()
        w.show()
        QApplication.processEvents()

        _find_shortcut(w, "Ctrl+S").activated.emit()

        w._save.assert_called_once()

    def test_no_shortcut_registered_when_save_absent(self, qtbot):
        from PyQt6.QtGui import QShortcut
        w = _KWidget()
        qtbot.addWidget(w)
        w.setup_keyboard()
        # Only the Escape shortcut should have been created.
        assert len(w.findChildren(QShortcut)) == 1


class TestEnterOnTable:
    def _table(self, qtbot):
        table = QTableWidget(2, 1)
        qtbot.addWidget(table)
        table.show()
        return table

    def test_on_enter_called_for_return_key(self, qtbot):
        w = _KWidget()
        qtbot.addWidget(w)
        table = self._table(qtbot)
        on_enter = MagicMock()

        w.setup_keyboard(table=table, on_enter=on_enter)
        qtbot.keyClick(table, Qt.Key.Key_Return)

        on_enter.assert_called_once()

    def test_falls_back_to_edit_method_when_no_on_enter(self, qtbot):
        w = _KWidget()
        qtbot.addWidget(w)
        w._edit = MagicMock()
        table = self._table(qtbot)

        w.setup_keyboard(table=table)
        qtbot.keyClick(table, Qt.Key.Key_Return)

        w._edit.assert_called_once()

    def test_non_enter_key_falls_through_to_original_handler(self, qtbot):
        w = _KWidget()
        qtbot.addWidget(w)
        table = self._table(qtbot)
        orig = MagicMock()
        table.keyPressEvent = orig
        on_enter = MagicMock()

        w.setup_keyboard(table=table, on_enter=on_enter)
        qtbot.keyClick(table, Qt.Key.Key_A)

        on_enter.assert_not_called()
        orig.assert_called_once()

    def test_keypress_unwrapped_when_no_enter_action_available(self, qtbot):
        w = _KWidget()
        qtbot.addWidget(w)
        table = self._table(qtbot)
        original_handler = table.keyPressEvent

        w.setup_keyboard(table=table)  # no on_enter, no self._edit

        assert table.keyPressEvent == original_handler
