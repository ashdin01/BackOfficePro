from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QDateEdit,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox, QTextEdit, QLabel
)
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QKeySequence, QShortcut
from utils.error_dialog import show_error
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
        # PO type hint
        hint = QLabel("Choose how to start this order:")
        hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.setSpacing(8)

        rec_btn = QPushButton("📋  Recommended PO  [Ctrl+R]")
        rec_btn.setFixedHeight(38)
        rec_btn.setDefault(False)
        rec_btn.setAutoDefault(False)
        rec_btn.setToolTip("Create PO pre-filled with products below reorder point")
        rec_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;font-weight:bold;padding:0 12px;}"
            "QPushButton:hover{background:#1976d2;}")
        rec_btn.clicked.connect(lambda: self._save(blank=False))

        blank_btn = QPushButton("➕  Blank PO  [Ctrl+B]")
        blank_btn.setFixedHeight(38)
        blank_btn.setDefault(False)
        blank_btn.setAutoDefault(False)
        blank_btn.setToolTip("Create an empty PO — add lines manually")
        blank_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;border:none;"
            "border-radius:4px;font-weight:bold;padding:0 12px;}"
            "QPushButton:hover{background:#388e3c;}")
        blank_btn.clicked.connect(lambda: self._save(blank=True))

        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(38)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.close)

        QShortcut(QKeySequence("Ctrl+R"), self, lambda: self._save(blank=False))
        QShortcut(QKeySequence("Ctrl+B"), self, lambda: self._save(blank=True))
        QShortcut(QKeySequence("Escape"), self, self.close)

        btns.addWidget(rec_btn)
        btns.addWidget(blank_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _save(self, blank=False):
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
            from views.purchase_orders.po_detail import PODetail
            self.detail_win = PODetail(po_id=po_id, on_save=self.on_save, blank=blank)
            self.detail_win.show()
            self.close()
        except Exception as e:
            show_error(self, "Could not create purchase order.", e)
