"""Purchase Orders settings screen — PO email (Microsoft Graph) config and PDF export folder."""
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QSizePolicy, QScrollArea,
)
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt
import config.styles as styles
import controllers.settings_controller as settings_ctrl
from utils.validators import validate_email
from utils.error_dialog import show_error
from utils.secret_store import get_secret, set_secret

GRAPH_FIELDS = [
    ("graph_client_id",      "Client ID",       "Azure App Registration Client ID"),
    ("graph_tenant_id",      "Tenant ID",       "Azure Directory (Tenant) ID"),
    ("graph_client_secret",  "Client Secret",   "Azure App Client Secret value"),
    ("graph_from_address",   "From Address",    "Microsoft 365 email address to send from"),
]

PATHS_FIELDS = [
    ("po_pdf_path", "PO PDF Folder", "Leave blank to use Documents/BackOfficePro/PurchaseOrders"),
]


class PurchaseOrdersScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Purchase Orders")
        self.setMinimumWidth(580)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._fields: dict[str, QLineEdit] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("Purchase Orders")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(scroll_widget)
        outer.addWidget(scroll, stretch=1)

        # ── Microsoft Graph API Configuration ─────────────────────────
        graph_group = QGroupBox("Email Configuration  (Microsoft 365 — for sending Purchase Orders)")
        graph_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        graph_form = QFormLayout(graph_group)
        graph_form.setContentsMargins(16, 16, 16, 16)
        graph_form.setSpacing(10)
        graph_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for key, label, placeholder in GRAPH_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumWidth(360)
            if key == "graph_client_secret":
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            graph_form.addRow(label, edit)
            self._fields[key] = edit

        btn_test = QPushButton("Test Connection")
        btn_test.setFixedHeight(30)
        btn_test.setStyleSheet(
            "QPushButton { background: #37474f; color: white; border: none; "
            "border-radius: 4px; padding: 0 12px; }"
            "QPushButton:hover { background: #455a64; }"
        )
        btn_test.clicked.connect(self._test_graph)
        graph_form.addRow("", btn_test)

        self._keyring_warn = QLabel(
            "⚠ Client Secret is stored as plaintext — the OS keychain (Windows Credential Manager) "
            "is unavailable on this machine. The secret is secure only if the database file is protected "
            "by OS-level file permissions. Re-enter and Save to retry keychain storage."
        )
        self._keyring_warn.setStyleSheet(
            f"color: {styles.CLR_WARNING}; font-size: 8pt; font-weight: bold;"
        )
        self._keyring_warn.setWordWrap(True)
        self._keyring_warn.setVisible(False)
        graph_form.addRow("", self._keyring_warn)

        note = QLabel(
            "💡 Requires an Azure App Registration with Mail.Send permission.\n"
            "    Azure Portal → App registrations → Your App → Certificates & secrets"
        )
        note.setStyleSheet("color: grey; font-size: 8pt;")
        note.setWordWrap(True)
        graph_form.addRow("", note)
        scroll_layout.addWidget(graph_group)

        # ── PO PDF Export ───────────────────────────────────────────────
        paths_group = QGroupBox("PO PDF Export")
        paths_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        paths_form = QFormLayout(paths_group)
        paths_form.setContentsMargins(16, 16, 16, 16)
        paths_form.setSpacing(10)
        paths_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, placeholder in PATHS_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumWidth(360)
            paths_form.addRow(label, edit)
            self._fields[key] = edit
        scroll_layout.addWidget(paths_group)

        scroll_layout.addStretch()

        # ── Buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(self.close)

        btn_save = QPushButton("Save  [Ctrl+S]")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
            f"border-radius: 4px; padding: 0 18px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
        )
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_save)
        outer.addLayout(btn_row)

        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        settings = settings_ctrl.get_all_settings()
        for key, edit in self._fields.items():
            edit.setText(settings.get(key, ""))

        # Migrate legacy plaintext secret from DB into keystore, then clear DB entry.
        # Only clear the DB copy if keyring storage confirmed success.
        db_secret = settings.get("graph_client_secret", "")
        keyring_secret = get_secret("graph_client_secret")
        using_db_fallback = False

        if db_secret and not keyring_secret:
            if set_secret("graph_client_secret", db_secret):
                keyring_secret = db_secret
                settings_ctrl.set_setting("graph_client_secret", "")
            else:
                keyring_secret = db_secret
                using_db_fallback = True

        if not keyring_secret and db_secret:
            keyring_secret = db_secret
            using_db_fallback = True

        self._keyring_warn.setVisible(using_db_fallback)
        self._fields["graph_client_secret"].setText(keyring_secret)

    def _save(self):
        errors = []

        try:
            from_val = validate_email(self._fields["graph_from_address"].text())
        except ValueError as e:
            errors.append(f"Graph From Address: {e}")
            from_val = None

        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
            return

        for key, edit in self._fields.items():
            if key == "graph_client_secret":
                secret_val = edit.text().strip()
                if not set_secret("graph_client_secret", secret_val):
                    # Keyring unavailable — store in DB as fallback (plaintext).
                    logging.warning("Keyring unavailable; storing graph_client_secret in DB.")
                    settings_ctrl.set_setting("graph_client_secret", secret_val)
                else:
                    settings_ctrl.set_setting("graph_client_secret", "")  # clear any DB copy
            elif key == "graph_from_address" and from_val is not None:
                settings_ctrl.set_setting(key, from_val)
            else:
                settings_ctrl.set_setting(key, edit.text().strip())

        QMessageBox.information(self, "Saved", "Purchase Orders settings saved successfully.")
        self.close()

    def _test_graph(self):
        graph_keys = {key for key, _, _ in GRAPH_FIELDS}
        for key, edit in self._fields.items():
            if key not in graph_keys:
                continue
            if key == "graph_client_secret":
                secret_val = edit.text().strip()
                if not set_secret("graph_client_secret", secret_val):
                    logging.warning("Keyring unavailable; storing graph_client_secret in DB.")
                    settings_ctrl.set_setting("graph_client_secret", secret_val)
                else:
                    settings_ctrl.set_setting("graph_client_secret", "")
            else:
                settings_ctrl.set_setting(key, edit.text().strip())
        try:
            from utils.email_graph import test_graph_connection
            success, message = test_graph_connection()
            if success:
                QMessageBox.information(self, "Connection Successful", message)
            else:
                QMessageBox.critical(self, "Connection Failed", message)
        except Exception as e:
            show_error(self, "Could not test Microsoft Graph connection.", e)
