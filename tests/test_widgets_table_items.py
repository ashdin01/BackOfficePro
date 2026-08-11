"""Tests for views/widgets/table_items.py — NumItem's numeric sort comparator.

Requires pytest-qt (installed) and a live display (DISPLAY=:0), since
QTableWidgetItem needs a QApplication instance.
"""
import pytest
from PyQt6.QtWidgets import QTableWidget

from views.widgets.table_items import NumItem


@pytest.fixture()
def table(qtbot):
    t = QTableWidget()
    qtbot.addWidget(t)
    t.setColumnCount(1)
    return t


class TestNumItemSort:
    def test_sorts_dollar_percent_comma_values_numerically(self, table):
        table.setRowCount(3)
        table.setSortingEnabled(False)
        table.setItem(0, 0, NumItem("$1,234.50"))
        table.setItem(1, 0, NumItem("5.0%"))
        table.setItem(2, 0, NumItem("$99.00"))
        table.setSortingEnabled(True)
        table.sortItems(0)
        assert [table.item(r, 0).text() for r in range(3)] == ["5.0%", "$99.00", "$1,234.50"]

    def test_non_numeric_placeholder_does_not_crash_sort_and_sorts_first(self, table):
        """Regression: mixing a parsed float with the raw string on either
        side of NumItem.__lt__ used to raise TypeError('<' not supported
        between instances of 'str' and 'float'), which aborts the whole
        process when Qt's C++ sort calls into it — not just a Python
        exception you can catch. Found while adding a GP% column that
        shows '--' for products with no sell price."""
        table.setRowCount(3)
        table.setSortingEnabled(False)
        table.setItem(0, 0, NumItem("12.3%"))
        table.setItem(1, 0, NumItem("--"))
        table.setItem(2, 0, NumItem("5.0%"))
        table.setSortingEnabled(True)
        table.sortItems(0)  # must not raise
        assert [table.item(r, 0).text() for r in range(3)] == ["--", "5.0%", "12.3%"]
