from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import math
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.stock_on_hand as stock_model
import models.product as product_model
from config.constants import PO_STATUS_RECEIVED, PO_STATUS_PARTIAL, MOVE_RECEIPT


class POReceive(QWidget):
    def __init__(self, po_id, on_save=None):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self.setWindowTitle("Receive Stock")
        self.setMinimumSize(1100, 560)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.header = QLabel()
        layout.addWidget(self.header)

        note = QLabel(
            "💡  Enter units received and item cost per unit.  "
            "Line Total = Receiving Now × Item Cost $."
        )
        note.setStyleSheet("color: #FFA500; font-size: 11px; padding: 4px 0;")
        layout.addWidget(note)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Pack Size",
            "Ordered (Units)", "Already Received",
            "Receiving Now", "Item Cost $", "Line Total $"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 2, 3, 4, 5, 6, 7]:
            hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 110)
        self.table.setColumnWidth(6, 110)
        self.table.setColumnWidth(7, 110)
        layout.addWidget(self.table)

        self.total_label = QLabel()
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.total_label)

        btns = QHBoxLayout()
        btn_receive = QPushButton("Confirm Receipt")
        btn_receive.setFixedHeight(35)
        btn_receive.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;font-weight:bold;"
            "border:none;border-radius:4px;padding:0 16px;}"
            "QPushButton:hover{background:#388e3c;}"
        )
        btn_receive.clicked.connect(self._confirm)
        btn_close = QPushButton("Close")
        btn_close.setFixedHeight(35)
        btn_close.clicked.connect(self.close)
        btns.addStretch()
        btns.addWidget(btn_receive)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _load(self):
        po = po_model.get_by_id(self.po_id)
        self.setWindowTitle(f"Receive: {po['po_number']}")
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} "
            f"— Status: <b>{po['status']}</b>"
        )
        self.lines = lines_model.get_by_po(self.po_id)
        self.table.setRowCount(0)
        # (line, pack_qty, qty_spinbox, cost_spinbox, line_total_item)
        self._inputs = []

        for line in self.lines:
            r = self.table.rowCount()
            self.table.insertRow(r)

            product   = product_model.get_by_barcode(line['barcode'])
            pack_qty  = int(product['pack_qty']) if product and product['pack_qty'] else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
            current_cost = float(product['cost_price']) if product else 0.0

            # Convert stored cartons → total units for display
            ordered_cartons  = int(line['ordered_qty'])
            ordered_units    = ordered_cartons * pack_qty
            received_cartons = int(line['received_qty'])
            received_units   = received_cartons * pack_qty
            remaining_units  = ordered_units - received_units

            # Barcode
            self.table.setItem(r, 0, QTableWidgetItem(line['barcode']))

            # Description
            desc_item = QTableWidgetItem(line['description'])
            self.table.setItem(r, 1, desc_item)

            # Pack size
            pack_item = QTableWidgetItem(
                f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit
            )
            pack_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 2, pack_item)

            # Ordered units
            ord_item = QTableWidgetItem(str(ordered_units))
            ord_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, ord_item)

            # Already received
            rec_item = QTableWidgetItem(str(received_units))
            rec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, rec_item)

            # Receiving Now spinner
            qty_input = QSpinBox()
            qty_input.setMinimum(0)
            qty_input.setMaximum(99999)
            qty_input.setSingleStep(pack_qty)
            qty_input.setValue(remaining_units)
            self.table.setCellWidget(r, 5, qty_input)

            # Item Cost $ spinner — pre-filled from product cost_price
            cost_input = QDoubleSpinBox()
            cost_input.setMinimum(0)
            cost_input.setMaximum(999999)
            cost_input.setDecimals(4)
            cost_input.setPrefix("$")
            cost_input.setValue(current_cost if current_cost > 0 else line['unit_cost'])
            cost_input.setToolTip("Cost per unit — updates product cost price on confirm")
            self.table.setCellWidget(r, 6, cost_input)

            # Line Total $ — read only, calculated
            lt_item = QTableWidgetItem("$0.00")
            lt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lt_item.setFlags(lt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 7, lt_item)

            # Connect signals after all widgets set
            qty_input.valueChanged.connect(lambda _, row=r: self._refresh_line(row))
            cost_input.valueChanged.connect(lambda _, row=r: self._refresh_line(row))

            self._inputs.append((line, pack_qty, qty_input, cost_input, lt_item))
            self._refresh_line(r)

        self._update_total()

    def _refresh_line(self, row):
        """Recalculate line total for a specific row."""
        if row >= len(self._inputs):
            return
        line, pack_qty, qty_input, cost_input, lt_item = self._inputs[row]
        qty  = qty_input.value()
        cost = cost_input.value()
        line_total = qty * cost
        lt_item.setText(f"${line_total:.2f}")
        self._update_total()

    def _update_total(self):
        total = 0.0
        for line, pack_qty, qty_input, cost_input, lt_item in self._inputs:
            try:
                val = float(lt_item.text().replace("$", "").replace(",", ""))
                total += val
            except (ValueError, AttributeError):
                pass
        self.total_label.setText(f"<b>Receipt Total: ${total:.2f}</b>")

    def _confirm(self):
        reply = QMessageBox.question(
            self, "Confirm Receipt", "Receive stock and update cost prices?")
        if reply != QMessageBox.StandardButton.Yes:
            return

        all_received = True
        for line, pack_qty, qty_input, cost_input, lt_item in self._inputs:
            qty       = qty_input.value()
            item_cost = cost_input.value()

            if qty > 0:
                # Convert units back to cartons for storage
                cartons = max(1, math.ceil(qty / pack_qty))

                # Update po_line received qty and unit_cost
                lines_model.receive(line['id'],
                                    line['received_qty'] + cartons,
                                    item_cost if item_cost > 0 else None)

                # Update unit_cost on po_line
                from database.connection import get_connection
                conn = get_connection()
                conn.execute(
                    "UPDATE po_lines SET unit_cost=? WHERE id=?",
                    (item_cost, line['id'])
                )
                conn.commit()
                conn.close()

                # Update stock on hand
                stock_model.adjust(
                    barcode=line['barcode'],
                    quantity=qty,
                    movement_type=MOVE_RECEIPT,
                    reference=f"PO-{self.po_id}",
                )

                # Update product cost_price if item_cost entered
                if item_cost > 0:
                    from database.connection import get_connection
                    conn = get_connection()
                    conn.execute(
                        "UPDATE products SET cost_price=?, updated_at=CURRENT_TIMESTAMP "
                        "WHERE barcode=?",
                        (item_cost, line['barcode'])
                    )
                    conn.commit()
                    conn.close()

            # Check if fully received
            total_received_cartons = line['received_qty'] + (
                max(1, math.ceil(qty / pack_qty)) if qty > 0 else 0
            )
            if total_received_cartons < line['ordered_qty']:
                all_received = False

        status = PO_STATUS_RECEIVED if all_received else PO_STATUS_PARTIAL
        po_model.update_status(self.po_id, status)
        if self.on_save:
            self.on_save()
        QMessageBox.information(self, "Done",
            f"Stock received. PO status: {status}")
        self.close()
