from PyQt6.QtWidgets import QTableWidget, QHeaderView


def make_table(headers: list[str], stretch_col: int = 1) -> QTableWidget:
    """Standard read-only table: alternating row colours, sorting, no vertical header."""
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setSortingEnabled(True)
    return t
