from PyQt6.QtWidgets import QLineEdit, QWidget
from PyQt6.QtCore import QTimer, pyqtSignal


class SearchBar(QLineEdit):
    """QLineEdit with a debounced search_changed signal.

    Emits search_changed after the user stops typing (default 350 ms).
    If focus_widget is given, pressing Return moves focus to that widget.
    """
    search_changed = pyqtSignal()

    def __init__(
        self,
        placeholder: str = "Search…",
        interval: int = 350,
        focus_widget: QWidget | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self.search_changed)
        self.textChanged.connect(lambda _: self._timer.start())
        if focus_widget is not None:
            self.returnPressed.connect(focus_widget.setFocus)
