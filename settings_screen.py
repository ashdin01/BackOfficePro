"""
Settings screen for BackOfficePro.
Allows editing of store details, email addresses and Microsoft Graph API configuration.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from database.connection import get_connection

SETTINGS_FIELDS = [
    # (db_key,              label,               placeholder)
    ("store_name",        "Store Name *",        "e.g. The Little Red Apple"),
    ("store_address",     "Address",             "e.g. 8795 Midland Highway Barkers Creek VIC 3451"),
    ("store_phone",       "Phone",               "e.g. (03) 54742483"),
    ("store_abn",         "ABN",                 "e.g. 12 345 678 901"),
]

EMAIL_FIELDS = [
    ("email_accounts",    "Accounts",            "Receiving invoices — e.g. accounts@yourbusiness.com.au"),
    ("email_purchasing",  "Purchasing",          "Sending purchase orders — e.g. purchasing@yourbusiness.com.au"),
    ("email_contact",     "Contact",             "Receiving enquiries — e.g. hello@yourbusiness.com.au"),
]

PATHS_FIELDS = [
    ("po_pdf_path", "PO PDF Folder", "Leave blank to use Documents/BackOfficePro/PurchaseOrders"),
]

GRAPH_FIELDS = [
    ("graph_client_id",      "Client ID",       "Azure App Registration Client ID"),
    ("graph_tenant_id",      "Tenant ID",       "Azure Directory (Tenant) ID"),
    ("graph_client_secret",  "Client Secret",   "Azure App Client Secret value"),
    ("graph_from_address",   "From Address",    "Microsoft 365 email address to send from"),
]


def _load_settings():
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r[0]: (r[1] or "") for r in rows}


def _save_setting(key: str, value: str):
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
        self.setMinimumWidth(580)
        self.setMinimumHeight(700)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._fields: dict[str, QLineEdit] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        outer.addWidget(title)

        # Scrollable area for all groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(scroll_widget)
        outer.addWidget(scroll, stretch=1)

        # ── Store Details ──────────────────────────────────────────────
        store_group = QGroupBox("Store Details")
        store_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        store_form = QFormLayout(store_group)
        store_form.setContentsMargins(16, 16, 16, 16)
        store_form.setSpacing(10)
        store_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, placeholder in SETTINGS_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumWidth(360)
            store_form.addRow(label, edit)
            self._fields[key] = edit
        scroll_layout.addWidget(store_group)

        # ── Email Addresses ────────────────────────────────────────────
        email_group = QGroupBox("Email Addresses")
        email_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        email_form = QFormLayout(email_group)
        email_form.setContentsMargins(16, 16, 16, 16)
        email_form.setSpacing(10)
        email_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, placeholder in EMAIL_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumWidth(360)
            email_form.addRow(label, edit)
            self._fields[key] = edit
        scroll_layout.addWidget(email_group)

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

        # Test connection button
        btn_test = QPushButton("Test Connection")
        btn_test.setFixedHeight(30)
        btn_test.setStyleSheet(
            "QPushButton { background: #37474f; color: white; border: none; "
            "border-radius: 4px; padding: 0 12px; }"
            "QPushButton:hover { background: #455a64; }"
        )
        btn_test.clicked.connect(self._test_graph)
        graph_form.addRow("", btn_test)

        note = QLabel(
            "💡 Requires an Azure App Registration with Mail.Send permission.\n"
            "    Azure Portal → App registrations → Your App → Certificates & secrets"
        )
        note.setStyleSheet("color: grey; font-size: 8pt;")
        note.setWordWrap(True)
        graph_form.addRow("", note)

        scroll_layout.addWidget(graph_group)
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
        settings = _load_settings()
        for key, edit in self._fields.items():
            edit.setText(settings.get(key, ""))

    def _save(self):
        if not self._fields["store_name"].text().strip():
            QMessageBox.warning(self, "Validation", "Store Name is required.")
            self._fields["store_name"].setFocus()
            return
        for key, edit in self._fields.items():
            _save_setting(key, edit.text().strip())
        QMessageBox.information(self, "Saved", "Settings saved successfully.")
        self.close()

    def _test_graph(self):
        # Save current field values first so the test uses what's on screen
        for key, edit in self._fields.items():
            _save_setting(key, edit.text().strip())
        try:
            from utils.email_graph import test_graph_connection
            success, message = test_graph_connection()
            if success:
                QMessageBox.information(self, "Connection Successful", message)
            else:
                QMessageBox.critical(self, "Connection Failed", message)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
