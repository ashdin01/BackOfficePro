from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QCheckBox, QSpinBox,
    QDoubleSpinBox, QTextEdit, QGroupBox, QMessageBox
)
from PyQt6.QtCore import Qt
import models.customer as customer_model


class CustomerEdit(QWidget):
    def __init__(self, customer_id=None, on_saved=None):
        super().__init__()
        self._id       = customer_id
        self._on_saved = on_saved
        self.setWindowTitle("Add Customer" if customer_id is None else "Edit Customer")
        self.setMinimumWidth(560)
        self.setWindowFlags(Qt.WindowType.Window)
        self._build_ui()
        if customer_id:
            self._populate()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Details ───────────────────────────────────────────────────
        grp = QGroupBox("Customer Details")
        form = QFormLayout(grp)

        self.code          = QLineEdit(); self.code.setMaxLength(20)
        self.name          = QLineEdit()
        self.abn           = QLineEdit(); self.abn.setMaxLength(20)
        self.contact       = QLineEdit()
        self.phone         = QLineEdit()
        self.email         = QLineEdit()

        form.addRow("Code *",         self.code)
        form.addRow("Name *",         self.name)
        form.addRow("ABN",            self.abn)
        form.addRow("Contact Name",   self.contact)
        form.addRow("Phone",          self.phone)
        form.addRow("Email",          self.email)
        root.addWidget(grp)

        # ── Address ───────────────────────────────────────────────────
        grp2 = QGroupBox("Address")
        f2   = QFormLayout(grp2)
        self.addr1    = QLineEdit()
        self.addr2    = QLineEdit()
        self.suburb   = QLineEdit()
        self.state    = QLineEdit(); self.state.setMaxLength(3)
        self.postcode = QLineEdit(); self.postcode.setMaxLength(4)
        f2.addRow("Address Line 1", self.addr1)
        f2.addRow("Address Line 2", self.addr2)
        f2.addRow("Suburb",         self.suburb)
        f2.addRow("State",          self.state)
        f2.addRow("Postcode",       self.postcode)
        root.addWidget(grp2)

        # ── Terms ─────────────────────────────────────────────────────
        grp3 = QGroupBox("Account Settings")
        f3   = QFormLayout(grp3)

        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setValue(37)
        self.terms.setSuffix(" days (EOM basis)")

        self.credit_limit = QDoubleSpinBox()
        self.credit_limit.setRange(0, 9999999)
        self.credit_limit.setPrefix("$")
        self.credit_limit.setDecimals(2)

        self.active = QCheckBox("Active")
        self.active.setChecked(True)

        f3.addRow("Payment Terms",  self.terms)
        f3.addRow("Credit Limit",   self.credit_limit)
        f3.addRow("",               self.active)
        root.addWidget(grp3)

        # ── Notes ─────────────────────────────────────────────────────
        grp4 = QGroupBox("Notes")
        f4   = QVBoxLayout(grp4)
        self.notes = QTextEdit(); self.notes.setMaximumHeight(80)
        f4.addWidget(self.notes)
        root.addWidget(grp4)

        # ── Buttons ───────────────────────────────────────────────────
        btns = QHBoxLayout()
        btn_save   = QPushButton("&Save")
        btn_cancel = QPushButton("Cancel")
        btn_save.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.close)
        btns.addStretch()
        btns.addWidget(btn_save)
        btns.addWidget(btn_cancel)
        root.addLayout(btns)

    def _populate(self):
        c = customer_model.get_by_id(self._id)
        if not c:
            return
        self.code.setText(c.get('code', ''))
        self.name.setText(c.get('name', ''))
        self.abn.setText(c.get('abn', ''))
        self.contact.setText(c.get('contact_name', ''))
        self.phone.setText(c.get('phone', ''))
        self.email.setText(c.get('email', ''))
        self.addr1.setText(c.get('address_line1', ''))
        self.addr2.setText(c.get('address_line2', ''))
        self.suburb.setText(c.get('suburb', ''))
        self.state.setText(c.get('state', ''))
        self.postcode.setText(c.get('postcode', ''))
        self.terms.setValue(int(c.get('payment_terms_days', 37)))
        self.credit_limit.setValue(float(c.get('credit_limit', 0) or 0))
        self.active.setChecked(bool(c.get('active', 1)))
        self.notes.setPlainText(c.get('notes', ''))
        if self._id:
            self.code.setReadOnly(True)

    def _save(self):
        code = self.code.text().strip().upper()
        name = self.name.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Validation", "Code and Name are required.")
            return
        kwargs = dict(
            code=code, name=name,
            abn=self.abn.text().strip(),
            address_line1=self.addr1.text().strip(),
            address_line2=self.addr2.text().strip(),
            suburb=self.suburb.text().strip(),
            state=self.state.text().strip().upper(),
            postcode=self.postcode.text().strip(),
            email=self.email.text().strip(),
            phone=self.phone.text().strip(),
            contact_name=self.contact.text().strip(),
            payment_terms_days=self.terms.value(),
            credit_limit=self.credit_limit.value(),
            active=1 if self.active.isChecked() else 0,
            notes=self.notes.toPlainText().strip(),
        )
        try:
            if self._id is None:
                customer_model.add(**kwargs)
            else:
                customer_model.update(self._id, **kwargs)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        if self._on_saved:
            self._on_saved()
        self.close()
