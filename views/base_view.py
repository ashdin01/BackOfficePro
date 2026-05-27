from PyQt6.QtWidgets import QWidget, QDialog
from utils.error_dialog import show_error


class BaseView(QWidget):
    """Base class for all main-panel views.

    Subclasses override _load() with their data-fetch logic.
    Call self.load() (not self._load()) from __init__, showEvent, and
    action handlers so errors are caught and shown to the user.
    """

    def load(self):
        try:
            self._load()
        except Exception as exc:
            show_error(self, "Failed to load data", exc)

    def _load(self):
        pass


class BaseDialog(QDialog):
    """Base class for modal dialogs that load data on open."""

    def load(self):
        try:
            self._load()
        except Exception as exc:
            show_error(self, "Failed to load data", exc)

    def _load(self):
        pass
