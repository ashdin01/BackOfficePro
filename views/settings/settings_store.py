"""Store Details settings screen — store identity and contact emails."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import config.styles as styles
import controllers.settings_controller as settings_ctrl
from utils.validators import validate_abn, validate_email, validate_phone

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


class StoreDetailsScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Store Details")
        self.setMinimumWidth(580)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._fields: dict[str, QLineEdit] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("Store Details")
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

    def _save(self):
        errors = []

        if not self._fields["store_name"].text().strip():
            errors.append("Store Name is required.")

        abn_val = ""
        try:
            abn_val = validate_abn(self._fields["store_abn"].text())
        except ValueError as e:
            errors.append(f"ABN: {e}")

        phone_val = ""
        try:
            phone_val = validate_phone(self._fields["store_phone"].text())
        except ValueError as e:
            errors.append(f"Phone: {e}")

        email_keys = ["email_accounts", "email_purchasing", "email_contact"]
        email_labels = {
            "email_accounts":   "Accounts Email",
            "email_purchasing": "Purchasing Email",
            "email_contact":    "Contact Email",
        }
        email_vals = {}
        for key in email_keys:
            try:
                email_vals[key] = validate_email(self._fields[key].text())
            except ValueError as e:
                errors.append(f"{email_labels[key]}: {e}")

        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
            if not self._fields["store_name"].text().strip():
                self._fields["store_name"].setFocus()
            return

        if abn_val:
            self._fields["store_abn"].setText(abn_val)

        for key, edit in self._fields.items():
            if key == "store_abn" and abn_val:
                settings_ctrl.set_setting(key, abn_val)
            elif key == "store_phone" and phone_val:
                settings_ctrl.set_setting(key, phone_val)
            elif key in email_vals:
                settings_ctrl.set_setting(key, email_vals[key])
            else:
                settings_ctrl.set_setting(key, edit.text().strip())

        QMessageBox.information(self, "Saved", "Store Details saved successfully.")
        self.close()
