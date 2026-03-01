from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox, QTextEdit
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
        self.active = QCheckBox("Active")
        self.active.setChecked(True)
        form.addRow("Code *", self.code)
        form.addRow("Name *", self.name)
        form.addRow("Contact Name", self.contact)
        form.addRow("Phone", self.phone)
        form.addRow("Email", self.email)
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
            self.address.setText(s.get('address') or '')
            self.notes.setText(s['notes'] or '')
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
                    int(self.active.isChecked())
                )
            else:
                supplier_model.add(
                    code, name, self.contact.text(), self.phone.text(),
                    self.email.text(), self.account.text(),
                    self.terms.text(), self.address.toPlainText(),
                    self.notes.toPlainText()
                )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
