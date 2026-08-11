from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtCore import Qt

RIGHT  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
LEFT   = Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter


class NumItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically, stripping $, %, commas, +/-.

    Non-numeric placeholders (e.g. "--", "N/A") sort before all numeric
    values rather than raising — mixing a parsed float with the original
    string on either side of `<` crashes the whole app (str vs float is
    unorderable in Python 3), so both sides must always resolve to floats.
    """
    def __lt__(self, other):
        def _val(t):
            try:
                return float(
                    t.replace('$', '').replace('%', '')
                     .replace(',', '').replace('+', '').strip()
                )
            except ValueError:
                return float('-inf')
        return _val(self.text()) < _val(other.text())


def item(text: str, align=LEFT, numeric: bool = False) -> QTableWidgetItem:
    """Create a table item with the given alignment, optionally numeric-sortable."""
    i = NumItem(str(text)) if numeric else QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    return i


def right_item(text: str) -> NumItem:
    """Right-aligned, numeric-sortable table item."""
    i = NumItem(str(text))
    i.setTextAlignment(RIGHT)
    return i


def center_item(text: str) -> NumItem:
    """Centred, numeric-sortable table item."""
    i = NumItem(str(text))
    i.setTextAlignment(CENTER)
    return i
