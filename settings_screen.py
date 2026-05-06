"""
Settings screen for BackOfficePro.
Allows editing of store details, email addresses, Microsoft Graph API configuration,
and user management (add / edit / reset PIN / deactivate).
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QSizePolicy, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QComboBox, QDialogButtonBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QColor
from database.connection import get_connection
from utils.validators import validate_abn, validate_email, validate_phone
from utils.error_dialog import show_error
import models.user as user_model

SETTINGS_FIELDS = [
    # (db_key,              label,               placeholder)
    ("store_name",        "Store Name *",        "e.g. The Little Red Apple"),
    ("store_manager",     "Store Manager",       "e.g. Jane Smith"),
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

BACKUP_FIELDS = [
    ("backup_email", "Email backup to", "e.g. owner@yourbusiness.com.au — leave blank to disable"),
]

ROLES = ["ADMIN", "MANAGER", "STAFF"]


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


# ── User dialog ────────────────────────────────────────────────────────────────

class _UserDialog(QDialog):
    """Add or edit a user. Pass user=None for add mode."""

    def __init__(self, user=None, parent=None):
        super().__init__(parent)
        self._user = user
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setWindowTitle("Edit User" if user else "Add User")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._full_name = QLineEdit(self._user['full_name'] if self._user else '')
        self._full_name.setPlaceholderText("e.g. Jane Smith")
        form.addRow("Full Name *", self._full_name)

        self._username = QLineEdit(self._user['username'] if self._user else '')
        self._username.setPlaceholderText("e.g. jsmith  (used at login)")
        form.addRow("Username *", self._username)

        self._role = QComboBox()
        self._role.addItems(ROLES)
        if self._user:
            idx = self._role.findText(self._user['role'])
            if idx >= 0:
                self._role.setCurrentIndex(idx)
        form.addRow("Role *", self._role)

        # PIN fields — required for new users, optional for edit
        pin_label = "PIN (4–8 digits) *" if not self._user else "New PIN  (leave blank to keep)"
        self._pin = QLineEdit()
        self._pin.setPlaceholderText("4–8 digits")
        self._pin.setEchoMode(QLineEdit.EchoMode.Password)
        self._pin.setMaxLength(8)
        form.addRow(pin_label, self._pin)

        self._pin2 = QLineEdit()
        self._pin2.setPlaceholderText("Repeat PIN")
        self._pin2.setEchoMode(QLineEdit.EchoMode.Password)
        self._pin2.setMaxLength(8)
        form.addRow("Confirm PIN *" if not self._user else "Confirm PIN", self._pin2)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._full_name.setFocus()

    def _validate(self):
        full_name = self._full_name.text().strip()
        username  = self._username.text().strip().lower()
        role      = self._role.currentText()
        pin       = self._pin.text().strip()
        pin2      = self._pin2.text().strip()

        if not full_name:
            QMessageBox.warning(self, "Validation", "Full Name is required.")
            self._full_name.setFocus()
            return
        if not username:
            QMessageBox.warning(self, "Validation", "Username is required.")
            self._username.setFocus()
            return

        if not self._user:
            # Add mode — PIN required
            if not pin:
                QMessageBox.warning(self, "Validation", "PIN is required for new users.")
                self._pin.setFocus()
                return

        if pin:
            if not pin.isdigit() or not (4 <= len(pin) <= 8):
                QMessageBox.warning(self, "Validation", "PIN must be 4–8 digits.")
                self._pin.setFocus()
                return
            if pin != pin2:
                QMessageBox.warning(self, "Validation", "PINs do not match.")
                self._pin2.setFocus()
                return

        self.result_data = {
            'full_name': full_name,
            'username':  username,
            'role':      role,
            'pin':       pin or None,
        }
        self.accept()


# ── Main settings screen ───────────────────────────────────────────────────────

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

        # ── Backup ────────────────────────────────────────────────────
        backup_group = QGroupBox("Backup")
        backup_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        backup_form = QFormLayout(backup_group)
        backup_form.setContentsMargins(16, 16, 16, 16)
        backup_form.setSpacing(10)
        backup_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, placeholder in BACKUP_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumWidth(360)
            backup_form.addRow(label, edit)
            self._fields[key] = edit
        backup_note = QLabel(
            "💡 Uses the Microsoft 365 email configuration above.\n"
            "    The database backup is attached and sent automatically on app close."
        )
        backup_note.setStyleSheet("color: grey; font-size: 8pt;")
        backup_note.setWordWrap(True)
        backup_form.addRow("", backup_note)
        scroll_layout.addWidget(backup_group)

        # ── Users ─────────────────────────────────────────────────────
        users_group = QGroupBox("Users")
        users_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        users_layout = QVBoxLayout(users_group)
        users_layout.setContentsMargins(16, 16, 16, 16)
        users_layout.setSpacing(8)

        self._users_table = QTableWidget()
        self._users_table.setColumnCount(4)
        self._users_table.setHorizontalHeaderLabels(["Full Name", "Username", "Role", "Status"])
        self._users_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._users_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self._users_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._users_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._users_table.setColumnWidth(1, 130)
        self._users_table.setColumnWidth(2, 90)
        self._users_table.setColumnWidth(3, 80)
        self._users_table.setFixedHeight(180)
        self._users_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._users_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._users_table.verticalHeader().setVisible(False)
        self._users_table.setAlternatingRowColors(True)
        self._users_table.doubleClicked.connect(self._edit_user)
        users_layout.addWidget(self._users_table)

        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(6)

        btn_add = QPushButton("+ Add User")
        btn_add.setFixedHeight(30)
        btn_add.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:0 12px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        btn_add.clicked.connect(self._add_user)

        self._btn_edit = QPushButton("Edit")
        self._btn_edit.setFixedHeight(30)
        self._btn_edit.setEnabled(False)
        self._btn_edit.clicked.connect(self._edit_user)

        self._btn_reset_pin = QPushButton("Reset PIN")
        self._btn_reset_pin.setFixedHeight(30)
        self._btn_reset_pin.setEnabled(False)
        self._btn_reset_pin.clicked.connect(self._reset_pin)

        self._btn_toggle = QPushButton("Deactivate")
        self._btn_toggle.setFixedHeight(30)
        self._btn_toggle.setEnabled(False)
        self._btn_toggle.setStyleSheet(
            "QPushButton{color:#f44336;border:1px solid #f44336;"
            "border-radius:4px;padding:0 12px;background:transparent;}"
            "QPushButton:hover{background:#2d1010;}"
            "QPushButton:disabled{color:#555;border-color:#333;}"
        )
        self._btn_toggle.clicked.connect(self._toggle_active)

        btn_bar.addWidget(btn_add)
        btn_bar.addWidget(self._btn_edit)
        btn_bar.addWidget(self._btn_reset_pin)
        btn_bar.addStretch()
        btn_bar.addWidget(self._btn_toggle)
        users_layout.addLayout(btn_bar)

        self._users_table.selectionModel().selectionChanged.connect(self._on_user_selection)
        scroll_layout.addWidget(users_group)

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

    # ── Settings load / save ───────────────────────────────────────────

    def _load(self):
        settings = _load_settings()
        for key, edit in self._fields.items():
            edit.setText(settings.get(key, ""))
        self._load_users()

    def _save(self):
        errors = []

        if not self._fields["store_name"].text().strip():
            errors.append("Store Name is required.")

        # ABN
        abn_val = ""
        try:
            abn_val = validate_abn(self._fields["store_abn"].text())
        except ValueError as e:
            errors.append(f"ABN: {e}")

        # Phone
        phone_val = ""
        try:
            phone_val = validate_phone(self._fields["store_phone"].text())
        except ValueError as e:
            errors.append(f"Phone: {e}")

        # Email fields
        email_keys = ["email_accounts", "email_purchasing", "email_contact",
                      "graph_from_address", "backup_email"]
        email_labels = {
            "email_accounts":   "Accounts Email",
            "email_purchasing": "Purchasing Email",
            "email_contact":    "Contact Email",
            "graph_from_address": "Graph From Address",
            "backup_email":     "Backup Email",
        }
        email_vals = {}
        for key in email_keys:
            if key not in self._fields:
                continue
            try:
                email_vals[key] = validate_email(self._fields[key].text())
            except ValueError as e:
                errors.append(f"{email_labels[key]}: {e}")

        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
            if not self._fields["store_name"].text().strip():
                self._fields["store_name"].setFocus()
            return

        # Normalise ABN display
        if abn_val:
            self._fields["store_abn"].setText(abn_val)

        for key, edit in self._fields.items():
            if key == "store_abn" and abn_val:
                _save_setting(key, abn_val)
            elif key == "store_phone" and phone_val:
                _save_setting(key, phone_val)
            elif key in email_vals:
                _save_setting(key, email_vals[key])
            else:
                _save_setting(key, edit.text().strip())

        QMessageBox.information(self, "Saved", "Settings saved successfully.")
        self.close()

    def _test_graph(self):
        graph_keys = {key for key, _, _ in GRAPH_FIELDS}
        for key, edit in self._fields.items():
            if key in graph_keys:
                _save_setting(key, edit.text().strip())
        try:
            from utils.email_graph import test_graph_connection
            success, message = test_graph_connection()
            if success:
                QMessageBox.information(self, "Connection Successful", message)
            else:
                QMessageBox.critical(self, "Connection Failed", message)
        except Exception as e:
            show_error(self, "Could not test Microsoft Graph connection.", e)

    # ── User management ────────────────────────────────────────────────

    def _load_users(self):
        self._users_table.setRowCount(0)
        for u in user_model.get_all():
            r = self._users_table.rowCount()
            self._users_table.insertRow(r)
            self._users_table.setRowHeight(r, 26)

            name_item = QTableWidgetItem(u['full_name'] or '')
            name_item.setData(Qt.ItemDataRole.UserRole, u['id'])
            self._users_table.setItem(r, 0, name_item)
            self._users_table.setItem(r, 1, QTableWidgetItem(u['username']))

            role_item = QTableWidgetItem(u['role'])
            role_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._users_table.setItem(r, 2, role_item)

            active = bool(u['active'])
            status_item = QTableWidgetItem("Active" if active else "Inactive")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("#4CAF50" if active else "#f44336"))
            self._users_table.setItem(r, 3, status_item)

            if not active:
                for col in range(4):
                    item = self._users_table.item(r, col)
                    if item:
                        item.setForeground(QColor("#666"))

    def _selected_user_id(self):
        row = self._users_table.currentRow()
        if row < 0:
            return None
        item = self._users_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_user_selection(self):
        uid = self._selected_user_id()
        has_sel = uid is not None
        self._btn_edit.setEnabled(has_sel)
        self._btn_reset_pin.setEnabled(has_sel)
        self._btn_toggle.setEnabled(has_sel)
        if has_sel:
            row = self._users_table.currentRow()
            status = self._users_table.item(row, 3).text() if self._users_table.item(row, 3) else ""
            self._btn_toggle.setText("Reactivate" if status == "Inactive" else "Deactivate")

    def _add_user(self):
        dlg = _UserDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        d = dlg.result_data
        try:
            user_model.create(d['username'], d['full_name'], d['role'], d['pin'])
        except Exception as e:
            show_error(self, "Could not create user.", e)
            return
        self._load_users()

    def _edit_user(self):
        uid = self._selected_user_id()
        if uid is None:
            return
        all_users = user_model.get_all()
        user = next((u for u in all_users if u['id'] == uid), None)
        if not user:
            return
        dlg = _UserDialog(user=user, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        d = dlg.result_data
        try:
            user_model.update(uid, d['username'], d['full_name'], d['role'])
            if d['pin']:
                user_model.set_pin_by_id(uid, d['pin'])
        except Exception as e:
            show_error(self, "Could not update user.", e)
            return
        self._load_users()

    def _reset_pin(self):
        uid = self._selected_user_id()
        if uid is None:
            return
        row = self._users_table.currentRow()
        name = self._users_table.item(row, 0).text() if self._users_table.item(row, 0) else "user"

        pin, ok = _PinInputDialog.get_pin(f"New PIN for {name}", parent=self)
        if not ok or not pin:
            return
        try:
            user_model.set_pin_by_id(uid, pin)
            QMessageBox.information(self, "Done", f"PIN updated for {name}.")
        except Exception as e:
            show_error(self, "Could not update PIN.", e)

    def _toggle_active(self):
        uid = self._selected_user_id()
        if uid is None:
            return
        row = self._users_table.currentRow()
        name   = self._users_table.item(row, 0).text() if self._users_table.item(row, 0) else "user"
        status = self._users_table.item(row, 3).text() if self._users_table.item(row, 3) else ""
        going_active = (status == "Inactive")

        if not going_active:
            reply = QMessageBox.question(
                self, "Deactivate User",
                f"Deactivate {name}?\nThey will no longer be able to log in.",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        user_model.set_active(uid, going_active)
        self._load_users()


# ── Simple PIN input dialog ────────────────────────────────────────────────────

class _PinInputDialog(QDialog):
    def __init__(self, prompt, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reset PIN")
        self.setModal(True)
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(QLabel(prompt))

        self._pin = QLineEdit()
        self._pin.setPlaceholderText("4–8 digits")
        self._pin.setEchoMode(QLineEdit.EchoMode.Password)
        self._pin.setMaxLength(8)
        layout.addWidget(self._pin)

        self._pin2 = QLineEdit()
        self._pin2.setPlaceholderText("Confirm PIN")
        self._pin2.setEchoMode(QLineEdit.EchoMode.Password)
        self._pin2.setMaxLength(8)
        layout.addWidget(self._pin2)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self):
        pin  = self._pin.text().strip()
        pin2 = self._pin2.text().strip()
        if not pin.isdigit() or not (4 <= len(pin) <= 8):
            QMessageBox.warning(self, "Validation", "PIN must be 4–8 digits.")
            return
        if pin != pin2:
            QMessageBox.warning(self, "Validation", "PINs do not match.")
            return
        self._result = pin
        self.accept()

    @staticmethod
    def get_pin(prompt, parent=None):
        dlg = _PinInputDialog(prompt, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._result, True
        return None, False
