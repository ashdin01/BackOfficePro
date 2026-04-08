"""
Settings screen for BackOfficePro.
Allows editing of store details used on Purchase Order PDFs and throughout the app.

INSTALLATION:
1. Copy this file to your BackOfficePro directory (same level as main.py)
2. In your main window file, import and add a Settings button/menu item that opens:
       from settings_screen import SettingsScreen
       screen = SettingsScreen()
       screen.show()
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from database.connection import get_connection


# Keys managed by this screen, in display order
SETTINGS_FIELDS = [
    # (db_key,          label,                    placeholder)
    ("store_name",    "Store Name *",            "e.g. The Little Red Apple"),
    ("store_address", "Address",                 "e.g. 8795 Midland Highway Barkers Creek VIC 3451"),
    ("store_phone",   "Phone",                   "e.g. (03) 54742483"),
    ("store_abn",     "ABN",                     "e.g. 12 345 678 901"),
    ("store_email",   "Email",                   "e.g. info@yourbusiness.com.au"),
]


def _load_settings():
    """Return all settings as a dict {key: value}."""
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r[0]: (r[1] or "") for r in rows}


def _save_setting(key: str, value: str):
    """Insert or update a single setting."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value)
    )
    conn.commit()
    conn.close()


class SettingsScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._fields: dict[str, QLineEdit] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        # ── Title ──────────────────────────────────────────────────────
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        outer.addWidget(title)

        # ── Store Details group ────────────────────────────────────────
        group = QGroupBox("Store Details")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        form = QFormLayout(group)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for key, label, placeholder in SETTINGS_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumWidth(340)
            form.addRow(label, edit)
            self._fields[key] = edit

        outer.addWidget(group)

        # ── Note ───────────────────────────────────────────────────────
        note = QLabel("* Store Name appears on all Purchase Order PDFs.")
        note.setStyleSheet("color: grey; font-size: 8pt;")
        outer.addWidget(note)

        # ── Buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(self.close)

        btn_save = QPushButton("Save  [Ctrl+S]")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border: none; "
            "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
            "QPushButton:hover { background: #1976d2; }"
        )
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_save)
        outer.addLayout(btn_row)

        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        """Populate fields from the database."""
        settings = _load_settings()
        for key, edit in self._fields.items():
            edit.setText(settings.get(key, ""))

    def _save(self):
        store_name = self._fields["store_name"].text().strip()
        if not store_name:
            QMessageBox.warning(self, "Validation", "Store Name is required.")
            self._fields["store_name"].setFocus()
            return

        for key, edit in self._fields.items():
            _save_setting(key, edit.text().strip())

        QMessageBox.information(self, "Saved", "Settings saved successfully.")
        self.close()
