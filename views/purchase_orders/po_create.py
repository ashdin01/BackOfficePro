from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QDateEdit,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox, QTextEdit, QLabel
)
from PyQt6.QtCore import QDate
import models.purchase_order as po_model
import models.supplier as supplier_model


class POCreate(QWidget):
    def __init__(self, on_save=None):
        super().__init__()
        self.setWindowTitle("New Purchase Order")
        self.setMinimumWidth(400)
        self.on_save = on_save
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.supplier = QComboBox()
        suppliers = supplier_model.get_all()
        for s in suppliers:
            self.supplier.addItem(s['name'], s['id'])

        self.delivery_date = QDateEdit()
        self.delivery_date.setCalendarPopup(True)
        self.delivery_date.setDate(QDate.currentDate().addDays(7))
        self.delivery_date.setDisplayFormat("dd/MM/yyyy")

        self.notes = QTextEdit()
        self.notes.setMaximumHeight(80)
        self.notes.setPlaceholderText("Optional notes...")

        form.addRow("Supplier *", self.supplier)
        form.addRow("Expected Delivery", self.delivery_date)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        save_btn = QPushButton("Create PO")
        save_btn.setFixedHeight(35)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _save(self):
        supplier_id = self.supplier.currentData()
        if not supplier_id:
            QMessageBox.warning(self, "Validation", "Please select a supplier.")
            return
        try:
            po_id = po_model.create(
                supplier_id=supplier_id,
                delivery_date=self.delivery_date.date().toString("yyyy-MM-dd"),
                notes=self.notes.toPlainText(),
            )
            if self.on_save:
                self.on_save()
            # Open the PO detail straight away
            from views.purchase_orders.po_detail import PODetail
            self.detail_win = PODetail(po_id=po_id, on_save=self.on_save)
            self.detail_win.show()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
