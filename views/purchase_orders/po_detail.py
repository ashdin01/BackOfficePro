from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QDoubleSpinBox, QComboBox, QDialog, QFormLayout
)
from PyQt6.QtCore import Qt
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.product as product_model
from config.constants import PO_STATUS_SENT


class PODetail(QWidget):
    def __init__(self, po_id, on_save=None):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self.setMinimumSize(800, 600)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        self.header = QLabel()
        layout.addWidget(self.header)

        # Lines table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Ordered Qty", "Unit Cost", "Total", "Notes"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        # Totals
        self.total_label = QLabel()
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)

        # Buttons
        btns = QHBoxLayout()
        btn_add = QPushButton("+ Add Line")
        btn_add.clicked.connect(self._add_line)
        btn_del = QPushButton("Remove Line")
        btn_del.clicked.connect(self._remove_line)
        btn_send = QPushButton("Mark as Sent")
        btn_send.clicked.connect(self._mark_sent)
        btn_cancel = QPushButton("Cancel PO")
        btn_cancel.clicked.connect(self._cancel_po)
        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addStretch()
        btns.addWidget(btn_send)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def _load(self):
        po = po_model.get_by_id(self.po_id)
        self.setWindowTitle(f"PO: {po['po_number']}")
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — "
            f"Status: <b>{po['status']}</b> — "
            f"Delivery: {po['delivery_date'] or 'TBC'}"
        )
        lines = lines_model.get_by_po(self.po_id)
        self.table.setRowCount(0)
        total = 0
        for line in lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            line_total = line['ordered_qty'] * line['unit_cost']
            total += line_total
            self.table.setItem(r, 0, QTableWidgetItem(line['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(line['description']))
            self.table.setItem(r, 2, QTableWidgetItem(str(int(line['ordered_qty']))))
            self.table.setItem(r, 3, QTableWidgetItem(f"${line['unit_cost']:.2f}"))
            self.table.setItem(r, 4, QTableWidgetItem(f"${line_total:.2f}"))
            self.table.setItem(r, 5, QTableWidgetItem(line['notes'] or ''))
            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, line['id'])
        self.total_label.setText(f"<b>Order Total: ${total:.2f}</b>")

    def _add_line(self):
        dlg = AddLineDialog(self.po_id, parent=self)
        if dlg.exec():
            self._load()
            if self.on_save:
                self.on_save()

    def _remove_line(self):
        row = self.table.currentRow()
        if row < 0:
            return
        line_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Confirm", "Remove this line?")
        if reply == QMessageBox.StandardButton.Yes:
            lines_model.delete(line_id)
            self._load()

    def _mark_sent(self):
        reply = QMessageBox.question(self, "Confirm", "Mark this PO as Sent?")
        if reply == QMessageBox.StandardButton.Yes:
            po_model.update_status(self.po_id, PO_STATUS_SENT)
            self._load()
            if self.on_save:
                self.on_save()

    def _cancel_po(self):
        reply = QMessageBox.question(self, "Confirm", "Cancel this PO? This cannot be undone.")
        if reply == QMessageBox.StandardButton.Yes:
            po_model.cancel(self.po_id)
            self._load()
            if self.on_save:
                self.on_save()
            self.close()


class AddLineDialog(QDialog):
    def __init__(self, po_id, parent=None):
        super().__init__(parent)
        self.po_id = po_id
        self.setWindowTitle("Add Line")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")
        self.barcode.editingFinished.connect(self._lookup)

        self.description = QLineEdit()
        self.description.setPlaceholderText("Auto-filled on barcode lookup")

        self.qty = QDoubleSpinBox()
        self.qty.setMinimum(1)
        self.qty.setMaximum(99999)
        self.qty.setDecimals(0)
        self.qty.setValue(1)

        self.unit_cost = QDoubleSpinBox()
        self.unit_cost.setMaximum(99999)
        self.unit_cost.setPrefix("$")
        self.unit_cost.setDecimals(2)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional")

        # MOQ warning label
        self.moq_label = QLabel("")
        self.moq_label.setStyleSheet("color: orange;")
        self._reorder_qty = 0
        self.qty.valueChanged.connect(self._check_moq)

        form.addRow("Barcode *", self.barcode)
        form.addRow("Description", self.description)
        form.addRow("Qty *", self.qty)
        form.addRow("", self.moq_label)
        form.addRow("Unit Cost", self.unit_cost)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Add to PO")
        ok_btn.setFixedHeight(35)
        ok_btn.clicked.connect(self._add)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _lookup(self):
        barcode = self.barcode.text().strip()
        if not barcode:
            return
        product = product_model.get_by_barcode(barcode)
        if product:
            self.description.setText(product['description'])
            self.unit_cost.setValue(product['cost_price'])
            self._reorder_qty = int(product['reorder_qty']) if product['reorder_qty'] else 0
            self._check_moq()
        else:
            self.description.clear()

    def _check_moq(self):
        if self._reorder_qty > 0:
            qty = int(self.qty.value())
            if qty % self._reorder_qty != 0:
                self.moq_label.setText(
                    f"⚠ MOQ is {self._reorder_qty} units — please order in multiples of {self._reorder_qty}"
                )
            else:
                self.moq_label.setText("")
        else:
            self.moq_label.setText("")

    def _add(self):
        barcode = self.barcode.text().strip()
        description = self.description.text().strip()
        if not barcode or not description:
            QMessageBox.warning(self, "Validation", "Barcode and Description are required.")
            return
        qty = int(self.qty.value())
        # Hard MOQ check
        if self._reorder_qty > 0 and qty % self._reorder_qty != 0:
            reply = QMessageBox.warning(
                self, "MOQ Warning",
                f"Minimum order quantity is {self._reorder_qty}.\n"
                f"You entered {qty}. Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        lines_model.add(
            po_id=self.po_id,
            barcode=barcode,
            description=description,
            ordered_qty=qty,
            unit_cost=self.unit_cost.value(),
            notes=self.notes.text(),
        )
        self.accept()
