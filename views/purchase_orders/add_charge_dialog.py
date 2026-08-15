from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QPushButton,
    QComboBox, QLineEdit, QDoubleSpinBox, QMessageBox
)
from config.constants import PO_CHARGE_TYPES, PO_CHARGE_TYPE_ROUNDING
from utils.money_field import money_field

_STANDARD_RANGE = (0.00, 99999.99)
_ROUNDING_RANGE = (-9999.99, 9999.99)


class AddChargeDialog(QDialog):
    """Popup for adding a PO receiving charge — Freight, Fuel Levy, Rounding
    (positive or negative), or Other. Only ROUNDING may carry a negative
    amount; every other type is enforced non-negative here and again by
    models.purchase_order._validate_charges at receive time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Charge")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.type_combo = QComboBox()
        for code, label in PO_CHARGE_TYPES.items():
            self.type_combo.addItem(label, code)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Charge Type *", self.type_combo)

        self.desc_edit = QLineEdit()
        form.addRow("Description", self.desc_edit)

        self.tax_combo = QComboBox()
        self.tax_combo.addItem("GST (10%)", 10.0)
        self.tax_combo.addItem("GST Free (0%)", 0.0)
        form.addRow("Tax Type", self.tax_combo)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setDecimals(2)
        self.amount_spin.setRange(*_STANDARD_RANGE)
        form.addRow("Amount inc. Tax *", money_field(self.amount_spin))

        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("Add")
        ok_btn.setFixedHeight(32)
        ok_btn.setDefault(False)
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(self._on_add)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self._on_type_changed(0)

    def _on_type_changed(self, _index):
        code = self.type_combo.currentData()
        label = self.type_combo.currentText()
        # Keep description in sync with the picked type until the user
        # types something of their own.
        if not self.desc_edit.isModified():
            self.desc_edit.setText(label)

        if code == PO_CHARGE_TYPE_ROUNDING:
            self.amount_spin.setRange(*_ROUNDING_RANGE)
            self.amount_spin.setToolTip("Positive or negative — Rounding is the only charge type that may go negative.")
            idx = self.tax_combo.findData(0.0)
            if idx >= 0:
                self.tax_combo.setCurrentIndex(idx)
        else:
            self.amount_spin.setRange(*_STANDARD_RANGE)
            self.amount_spin.setToolTip("")

    def _on_add(self):
        code = self.type_combo.currentData()
        amount = self.amount_spin.value()
        if amount < 0 and code != PO_CHARGE_TYPE_ROUNDING:
            QMessageBox.warning(
                self, "Invalid Amount",
                "Only a Rounding charge can have a negative amount."
            )
            return
        if amount == 0:
            QMessageBox.warning(self, "Invalid Amount", "Enter a non-zero amount.")
            return
        self.accept()

    def data(self) -> dict:
        return {
            'charge_type':    self.type_combo.currentData(),
            'description':    self.desc_edit.text().strip() or self.type_combo.currentText(),
            'tax_rate':       self.tax_combo.currentData(),
            'amount_inc_tax': self.amount_spin.value(),
        }
