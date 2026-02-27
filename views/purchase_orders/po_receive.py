from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QSpinBox
)
from PyQt6.QtCore import Qt
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.stock_on_hand as stock_model
from config.constants import PO_STATUS_RECEIVED, PO_STATUS_PARTIAL, MOVE_RECEIPT


class POReceive(QWidget):
    def __init__(self, po_id, on_save=None):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self.setWindowTitle("Receive Stock")
        self.setMinimumSize(800, 500)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.header = QLabel()
        layout.addWidget(self.header)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Ordered", "Already Received", "Receiving Now"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        btns = QHBoxLayout()
        btn_receive = QPushButton("Confirm Receipt")
        btn_receive.setFixedHeight(35)
        btn_receive.clicked.connect(self._confirm)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(35)
        btn_cancel.clicked.connect(self.close)
        btns.addStretch()
        btns.addWidget(btn_receive)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def _load(self):
        po = po_model.get_by_id(self.po_id)
        self.setWindowTitle(f"Receive: {po['po_number']}")
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — Status: <b>{po['status']}</b>"
        )
        self.lines = lines_model.get_by_po(self.po_id)
        self.table.setRowCount(0)
        self._qty_inputs = []
        for line in self.lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(line['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(line['description']))
            self.table.setItem(r, 2, QTableWidgetItem(str(int(line['ordered_qty']))))
            self.table.setItem(r, 3, QTableWidgetItem(str(int(line['received_qty']))))
            remaining = int(line['ordered_qty']) - int(line['received_qty'])
            qty_input = QSpinBox()
            qty_input.setMinimum(0)
            qty_input.setMaximum(99999)
            qty_input.setValue(remaining)
            self.table.setCellWidget(r, 4, qty_input)
            self._qty_inputs.append((line, qty_input))

    def _confirm(self):
        reply = QMessageBox.question(self, "Confirm Receipt", "Receive stock for all lines?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        all_received = True
        for line, qty_input in self._qty_inputs:
            qty = qty_input.value()
            if qty > 0:
                lines_model.receive(line['id'], line['received_qty'] + qty)
                stock_model.adjust(
                    barcode=line['barcode'],
                    quantity=qty,
                    movement_type=MOVE_RECEIPT,
                    reference=f"PO-{self.po_id}",
                )
            total_received = line['received_qty'] + qty
            if total_received < line['ordered_qty']:
                all_received = False
        status = PO_STATUS_RECEIVED if all_received else PO_STATUS_PARTIAL
        po_model.update_status(self.po_id, status)
        if self.on_save:
            self.on_save()
        QMessageBox.information(self, "Done", f"Stock received. PO status: {status}")
        self.close()
