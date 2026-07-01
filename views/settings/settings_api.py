"""Stocktake / API settings screen — shared API key for Stocktake App and RetailPOSPro."""
import secrets as _secrets

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QSizePolicy, QApplication,
)
import config.styles as styles
from utils.api_key import resolve_api_key, store_api_key


class ApiAccessScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stocktake / API")
        self.setMinimumWidth(560)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("Stocktake / API")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        outer.addWidget(title)

        # ── API Access ────────────────────────────────────────────────
        api_group = QGroupBox("API Access  (Stocktake App / RetailPOSPro)")
        api_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        api_layout = QVBoxLayout(api_group)
        api_layout.setContentsMargins(16, 16, 16, 16)
        api_layout.setSpacing(8)

        api_note = QLabel(
            "All API clients must include this key as the X-API-Key request header."
        )
        api_note.setStyleSheet("color: grey; font-size: 8pt;")
        api_note.setWordWrap(True)
        api_layout.addWidget(api_note)

        key_row = QHBoxLayout()
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setReadOnly(True)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setMinimumWidth(300)
        key_row.addWidget(self._api_key_edit, stretch=1)

        btn_show_key = QPushButton("Show")
        btn_show_key.setFixedWidth(56)
        btn_show_key.setCheckable(True)
        btn_show_key.toggled.connect(
            lambda checked: self._api_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        key_row.addWidget(btn_show_key)

        btn_copy_key = QPushButton("Copy")
        btn_copy_key.setFixedWidth(56)
        btn_copy_key.clicked.connect(
            lambda: QApplication.clipboard().setText(self._api_key_edit.text())
        )
        key_row.addWidget(btn_copy_key)

        btn_regen_key = QPushButton("Regenerate")
        btn_regen_key.clicked.connect(self._regenerate_api_key)
        key_row.addWidget(btn_regen_key)

        api_layout.addLayout(key_row)
        outer.addWidget(api_group)

        outer.addStretch()

        # ── Buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_close = QPushButton("Close  [Esc]")
        btn_close.setFixedHeight(34)
        btn_close.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
            f"border-radius: 4px; padding: 0 18px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
        )
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        outer.addLayout(btn_row)

        from PyQt6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        self._load_api_key()

    def _load_api_key(self):
        # Must resolve through utils.api_key (keyring first, DB fallback) — the
        # API server resolves the same way, and reading only the DB here shows
        # a key the server won't accept on machines with a working keyring.
        self._api_key_edit.setText(resolve_api_key())

    def _regenerate_api_key(self):
        reply = QMessageBox.question(
            self, "Regenerate API Key",
            "This will invalidate the current key.\n"
            "All API clients (Stocktake App, RetailPOSPro) must be updated.\n\n"
            "Continue?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        key = _secrets.token_hex(32)
        store_api_key(key)
        self._api_key_edit.setText(key)
        QMessageBox.information(
            self, "Done",
            "New API key saved. Update all clients.\n\n"
            "The API server picks up the new key automatically — no restart needed."
        )
