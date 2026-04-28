from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox,
    QTextEdit, QDoubleSpinBox, QGroupBox
)
from utils.keyboard_mixin import KeyboardMixin
import models.supplier as supplier_model


class SupplierEdit(KeyboardMixin, QWidget):
    def __init__(self, supplier_id=None, on_save=None):
        super().__init__()
        self.supplier_id = supplier_id
        self.on_save = on_save
        self.setWindowTitle("Edit Supplier" if supplier_id else "Add Supplier")
        self.setMinimumWidth(440)
        self._build_ui()
        self.setup_keyboard()
        if supplier_id:
            self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Supplier Details ──────────────────────────────────────────
        details_group = QGroupBox("Supplier Details")
        details_form = QFormLayout(details_group)
        details_form.setSpacing(8)

        self.code    = QLineEdit()
        self.name    = QLineEdit()
        self.abn     = QLineEdit()
        self.contact = QLineEdit()
        self.phone   = QLineEdit()
        self.order_minimum = QDoubleSpinBox()
        self.order_minimum.setMaximum(999999)
        self.order_minimum.setPrefix("$")
        self.order_minimum.setDecimals(2)
        self.account = QLineEdit()
        self.terms   = QLineEdit()
        self.address = QTextEdit()
        self.address.setMaximumHeight(80)
        self.notes   = QTextEdit()
        self.notes.setMaximumHeight(80)
        self.active  = QCheckBox("Active")
        self.active.setChecked(True)

        details_form.addRow("Code *",         self.code)
        details_form.addRow("Company Name *", self.name)
        details_form.addRow("ABN",            self.abn)
        details_form.addRow("Contact Name",   self.contact)
        details_form.addRow("Phone",          self.phone)
        details_form.addRow("Order Minimum",  self.order_minimum)
        details_form.addRow("Account No.",    self.account)
        details_form.addRow("Payment Terms",  self.terms)
        details_form.addRow("Address",        self.address)
        details_form.addRow("Notes",          self.notes)
        details_form.addRow("",               self.active)
        layout.addWidget(details_group)

        # ── Sales Rep ─────────────────────────────────────────────────
        rep_group = QGroupBox("Sales Representative")
        rep_form = QFormLayout(rep_group)
        rep_form.setSpacing(8)

        self.rep_name  = QLineEdit()
        self.rep_phone = QLineEdit()
        self.email_rep = QLineEdit()
        self.email_rep.setPlaceholderText("e.g. diana@supplier.com.au")

        rep_form.addRow("Rep Name",  self.rep_name)
        rep_form.addRow("Rep Phone", self.rep_phone)
        rep_form.addRow("Rep Email", self.email_rep)
        layout.addWidget(rep_group)

        # ── Email Addresses ───────────────────────────────────────────
        email_group = QGroupBox("Email Addresses")
        email_form = QFormLayout(email_group)
        email_form.setSpacing(8)

        self.email_orders   = QLineEdit()
        self.email_admin    = QLineEdit()
        self.email_accounts = QLineEdit()

        self.email_orders.setPlaceholderText("e.g. orders@supplier.com.au")
        self.email_admin.setPlaceholderText("e.g. admin@supplier.com.au")
        self.email_accounts.setPlaceholderText("e.g. accounts@supplier.com.au")

        email_form.addRow("Orders",   self.email_orders)
        email_form.addRow("Admin",    self.email_admin)
        email_form.addRow("Accounts", self.email_accounts)
        layout.addWidget(email_group)

        # ── Online Ordering ───────────────────────────────────────────
        online_group = QGroupBox("Online Ordering")
        online_form = QFormLayout(online_group)
        online_form.setSpacing(8)

        self.online_order = QCheckBox("This supplier requires ordering via an online portal")
        self.online_order_note = QTextEdit()
        self.online_order_note.setMaximumHeight(70)
        self.online_order_note.setPlaceholderText(
            "e.g. Log in at https://portal.supplier.com.au and place order manually. Do NOT email this PO."
        )
        self.online_order_note.setEnabled(False)
        self.online_order.toggled.connect(self.online_order_note.setEnabled)

        online_form.addRow("", self.online_order)
        online_form.addRow("Instructions", self.online_order_note)
        layout.addWidget(online_group)

        # ── Buttons ───────────────────────────────────────────────────
        btns = QHBoxLayout()
        save_btn = QPushButton("Save  [Ctrl+S]")
        save_btn.setFixedHeight(35)
        save_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:0 18px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _populate(self):
        s = supplier_model.get_by_id(self.supplier_id)
        if not s:
            return
        keys = s.keys()
        self.code.setText(s['code'] or '')
        self.name.setText(s['name'] or '')
        self.abn.setText(s['abn'] if 'abn' in keys else '')
        self.contact.setText(s['contact_name'] or '')
        self.phone.setText(s['phone'] or '')
        self.account.setText(s['account_number'] or '')
        self.terms.setText(s['payment_terms'] or '')
        self.address.setText(s['address'] if 'address' in keys else '')
        self.notes.setText(s['notes'] or '')
        self.rep_name.setText(s['rep_name'] if 'rep_name' in keys else '')
        self.rep_phone.setText(s['rep_phone'] if 'rep_phone' in keys else '')
        self.order_minimum.setValue(
            float(s['order_minimum']) if 'order_minimum' in keys and s['order_minimum'] else 0
        )
        self.active.setChecked(bool(s['active']))

        # Email fields — fall back to legacy 'email' for orders if not yet migrated
        self.email_orders.setText(
            s['email_orders'] if 'email_orders' in keys and s['email_orders']
            else (s['email'] or '') if 'email' in keys else ''
        )
        self.email_admin.setText(s['email_admin'] if 'email_admin' in keys else '')
        self.email_accounts.setText(s['email_accounts'] if 'email_accounts' in keys else '')
        self.email_rep.setText(s['email_rep'] if 'email_rep' in keys else '')

        is_online = bool(s['online_order']) if 'online_order' in keys else False
        self.online_order.setChecked(is_online)
        self.online_order_note.setEnabled(is_online)
        self.online_order_note.setText(s['online_order_note'] if 'online_order_note' in keys else '')

    def _save(self):
        code = self.code.text().strip()
        name = self.name.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Validation", "Code and Name are required.")
            return
        try:
            if self.supplier_id:
                supplier_model.update(
                    self.supplier_id, code, name,
                    self.contact.text().strip(),
                    self.phone.text().strip(),
                    self.account.text().strip(),
                    self.terms.text().strip(),
                    self.address.toPlainText().strip(),
                    self.notes.toPlainText().strip(),
                    int(self.active.isChecked()),
                    abn=self.abn.text().strip(),
                    rep_name=self.rep_name.text().strip(),
                    rep_phone=self.rep_phone.text().strip(),
                    order_minimum=self.order_minimum.value(),
                    email_orders=self.email_orders.text().strip(),
                    email_admin=self.email_admin.text().strip(),
                    email_accounts=self.email_accounts.text().strip(),
                    email_rep=self.email_rep.text().strip(),
                    online_order=int(self.online_order.isChecked()),
                    online_order_note=self.online_order_note.toPlainText().strip(),
                )
            else:
                supplier_model.add(
                    code, name,
                    self.contact.text().strip(),
                    self.phone.text().strip(),
                    self.account.text().strip(),
                    self.terms.text().strip(),
                    self.address.toPlainText().strip(),
                    self.notes.toPlainText().strip(),
                    abn=self.abn.text().strip(),
                    rep_name=self.rep_name.text().strip(),
                    rep_phone=self.rep_phone.text().strip(),
                    order_minimum=self.order_minimum.value(),
                    email_orders=self.email_orders.text().strip(),
                    email_admin=self.email_admin.text().strip(),
                    email_accounts=self.email_accounts.text().strip(),
                    email_rep=self.email_rep.text().strip(),
                    online_order=int(self.online_order.isChecked()),
                    online_order_note=self.online_order_note.toPlainText().strip(),
                )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
