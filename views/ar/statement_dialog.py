import os
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QDialogButtonBox,
    QDateEdit, QMessageBox, QLabel
)
from PyQt6.QtCore import QDate
import models.customer as customer_model
import controllers.ar_controller as ar_ctrl


class StatementDialog(QDialog):
    def __init__(self, customer_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Statement")
        self.setMinimumWidth(360)
        self._build_ui(customer_id)

    def _build_ui(self, preselect_id):
        form = QFormLayout(self)

        self.cust_combo = QComboBox()
        customers = customer_model.get_all(active_only=True)
        for c in customers:
            self.cust_combo.addItem(f"{c['code']} — {c['name']}", c['id'])
        if preselect_id:
            for i in range(self.cust_combo.count()):
                if self.cust_combo.itemData(i) == preselect_id:
                    self.cust_combo.setCurrentIndex(i)
                    break
        form.addRow("Customer *", self.cust_combo)

        today = QDate.currentDate()
        first_of_month = QDate(today.year(), today.month(), 1)

        self.date_from = QDateEdit(first_of_month)
        self.date_from.setCalendarPopup(True)
        form.addRow("From *", self.date_from)

        self.date_to = QDateEdit(today)
        self.date_to.setCalendarPopup(True)
        form.addRow("To *", self.date_to)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._generate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _generate(self):
        cid       = self.cust_combo.currentData()
        date_from = self.date_from.date().toString("yyyy-MM-dd")
        date_to   = self.date_to.date().toString("yyyy-MM-dd")
        if date_from > date_to:
            QMessageBox.warning(self, "Validation", "'From' date must be before 'To' date.")
            return
        try:
            path = ar_ctrl.generate_statement_pdf(cid, date_from, date_to)
            QMessageBox.information(self, "Statement Saved", f"Saved to:\n{path}")
            os.startfile(path) if os.name == 'nt' else os.system(f'xdg-open "{path}"')
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
