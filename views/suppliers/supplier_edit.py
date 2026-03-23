from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox, QTextEdit, QDoubleSpinBox
)
from utils.keyboard_mixin import KeyboardMixin
import models.supplier as supplier_model

class SupplierEdit(KeyboardMixin, QWidget):
    def __init__(self, supplier_id=None, on_save=None):
        super().__init__()
        self.supplier_id = supplier_id
        self.on_save = on_save
        self.setWindowTitle("Edit Supplier" if supplier_id else "Add Supplier")
        self.setMinimumWidth(400)
        self._build_ui()
        self.setup_keyboard()
        if supplier_id:
            self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.code = QLineEdit()
        self.name = QLineEdit()
        self.contact = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.account = QLineEdit()
        self.terms = QLineEdit()
        self.address = QTextEdit()
        self.address.setMaximumHeight(80)
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(80)
        self.abn = QLineEdit()
        self.rep_name = QLineEdit()
        self.rep_phone = QLineEdit()
        self.order_minimum = QDoubleSpinBox()
        self.order_minimum.setMaximum(999999)
        self.order_minimum.setPrefix("$")
        self.order_minimum.setDecimals(2)
        self.active = QCheckBox("Active")
        self.active.setChecked(True)
        form.addRow("Code *", self.code)
        form.addRow("Company Name *", self.name)
        form.addRow("ABN", self.abn)
        form.addRow("Contact Name", self.contact)
        form.addRow("Phone", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Rep Name", self.rep_name)
        form.addRow("Rep Phone", self.rep_phone)
        form.addRow("Order Minimum", self.order_minimum)
        form.addRow("Account No.", self.account)
        form.addRow("Payment Terms", self.terms)
        form.addRow("Address", self.address)
        form.addRow("Notes", self.notes)
        form.addRow("", self.active)
        layout.addLayout(form)
        layout.addSpacing(10)
        btns = QHBoxLayout()
        save_btn = QPushButton("Save  [Ctrl+S]")
        save_btn.setFixedHeight(35)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _populate(self):
        s = supplier_model.get_by_id(self.supplier_id)
        if s:
            self.code.setText(s['code'])
            self.name.setText(s['name'])
            self.contact.setText(s['contact_name'] or '')
            self.phone.setText(s['phone'] or '')
            self.email.setText(s['email'] or '')
            self.account.setText(s['account_number'] or '')
            self.terms.setText(s['payment_terms'] or '')
            keys = s.keys()
            self.address.setText(s['address'] if 'address' in keys else '')
            self.notes.setText(s['notes'] or '')
            self.abn.setText(s['abn'] if 'abn' in keys else '')
            self.rep_name.setText(s['rep_name'] if 'rep_name' in keys else '')
            self.rep_phone.setText(s['rep_phone'] if 'rep_phone' in keys else '')
            self.order_minimum.setValue(float(s['order_minimum']) if 'order_minimum' in keys and s['order_minimum'] else 0)
            self.active.setChecked(bool(s['active']))

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
                    self.contact.text(), self.phone.text(),
                    self.email.text(), self.account.text(),
                    self.terms.text(), self.address.toPlainText(),
                    self.notes.toPlainText(),
                    int(self.active.isChecked()),
                    abn=self.abn.text().strip(),
                    rep_name=self.rep_name.text().strip(),
                    rep_phone=self.rep_phone.text().strip(),
                    order_minimum=self.order_minimum.value(),
                )
            else:
                supplier_model.add(
                    code, name, self.contact.text(), self.phone.text(),
                    self.email.text(), self.account.text(),
                    self.terms.text(), self.address.toPlainText(),
                    self.notes.toPlainText(),
                    abn=self.abn.text().strip(),
                    rep_name=self.rep_name.text().strip(),
                    rep_phone=self.rep_phone.text().strip(),
                    order_minimum=self.order_minimum.value(),
                )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
