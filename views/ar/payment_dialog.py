from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QDoubleSpinBox, QComboBox,
    QLineEdit, QDialogButtonBox, QLabel, QDateEdit
)
from PyQt6.QtCore import QDate
from datetime import date


class PaymentDialog(QDialog):
    def __init__(self, invoice, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Record Payment — {invoice['invoice_number']}")
        self.setMinimumWidth(380)
        self._inv = invoice
        self._build_ui()

    def _build_ui(self):
        form = QFormLayout(self)

        outstanding = round(float(self._inv['total']) - float(self._inv['amount_paid']), 2)
        form.addRow(QLabel(f"Outstanding: <b>${outstanding:.2f}</b>"))

        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 9999999)
        self.amount.setDecimals(2)
        self.amount.setPrefix("$")
        self.amount.setValue(outstanding)
        form.addRow("Amount *", self.amount)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        form.addRow("Payment Date *", self.date_edit)

        self.method = QComboBox()
        self.method.addItems(['EFT', 'CASH', 'CHEQUE', 'OTHER'])
        form.addRow("Method", self.method)

        self.reference = QLineEdit()
        self.reference.setPlaceholderText("Bank ref, cheque no, etc.")
        form.addRow("Reference", self.reference)

        self.notes = QLineEdit()
        form.addRow("Notes", self.notes)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def data(self):
        return {
            'amount':    self.amount.value(),
            'date':      self.date_edit.date().toString("yyyy-MM-dd"),
            'method':    self.method.currentText(),
            'reference': self.reference.text().strip(),
            'notes':     self.notes.text().strip(),
        }
