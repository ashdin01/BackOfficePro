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
        self.setMinimumSize(960, 540)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header = QLabel()
        layout.addWidget(self.header)

        note = QLabel(
            "💡  Fixed items: enter units received.  "
            "Variable weight items: enter actual invoice total $ for that line."
        )
        note.setStyleSheet("color: #FFA500; font-size: 11px; padding: 4px 0;")
        layout.addWidget(note)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Pack Size",
            "Ordered (Units)", "Already Received", "Receiving Now", "Actual Cost $"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 2, 3, 4, 5, 6]:
            hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 120)
        self.table.setColumnWidth(6, 120)
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
        # (line, pack_qty, qty_spinbox, cost_spinbox, is_var_wt)
        self._inputs = []

        for line in self.lines:
            r = self.table.rowCount()
            self.table.insertRow(r)

            product   = product_model.get_by_barcode(line['barcode'])
            is_var_wt = bool(product and product['variable_weight'])
            pack_qty  = int(product['pack_qty']) if product and product['pack_qty'] else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'

            # Convert stored cartons → total units for display
            ordered_cartons  = int(line['ordered_qty'])
            ordered_units    = ordered_cartons * pack_qty
            received_cartons = int(line['received_qty'])
            received_units   = received_cartons * pack_qty
            remaining_units  = ordered_units - received_units

            self.table.setItem(r, 0, QTableWidgetItem(line['barcode']))

            desc_item = QTableWidgetItem(line['description'])
            if is_var_wt:
                desc_item.setForeground(QColor("#FFA500"))
            self.table.setItem(r, 1, desc_item)

            # Pack size column
            pack_item = QTableWidgetItem(
                f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit
            )
            pack_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 2, pack_item)

            # Ordered in total units
            ord_item = QTableWidgetItem(str(ordered_units))
            ord_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, ord_item)

            # Already received in total units
            rec_item = QTableWidgetItem(str(received_units))
            rec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, rec_item)

            # Receiving Now spinner — in total units, snaps to pack_qty multiples
            qty_input = QSpinBox()
            qty_input.setMinimum(0)
            qty_input.setMaximum(99999)
            qty_input.setSingleStep(pack_qty)   # step by carton
            qty_input.setValue(remaining_units)
            qty_input.valueChanged.connect(self._update_total)
            self.table.setCellWidget(r, 5, qty_input)

            # Actual cost spinner
            cost_input = QDoubleSpinBox()
            cost_input.setMinimum(0)
            cost_input.setMaximum(999999)
            cost_input.setDecimals(2)
            cost_input.setPrefix("$")
            cost_input.valueChanged.connect(self._update_total)

            if is_var_wt:
                cost_input.setValue(0.00)
                cost_input.setStyleSheet("background: #2a1f00;")
                cost_input.setToolTip("Enter actual invoice total $ for this line")
            else:
                estimated = remaining_units * line['unit_cost']
                cost_input.setValue(estimated)
                cost_input.setEnabled(False)
                cost_input.setStyleSheet("color: #666;")
                cost_input.setToolTip("Auto-calculated from units × unit cost")

            self.table.setCellWidget(r, 6, cost_input)
            self._inputs.append((line, pack_qty, qty_input, cost_input, is_var_wt))

        self._update_total()

    def _update_total(self):
        fixed_total = 0.0
        var_total   = 0.0
        var_entered = 0
        var_lines   = 0

        for line, pack_qty, qty_input, cost_input, is_var_wt in self._inputs:
            qty = qty_input.value()
            if is_var_wt:
                var_lines += 1
                cost = cost_input.value()
                var_total += cost
                if cost > 0:
                    var_entered += 1
                cost_input.setEnabled(True)
            else:
                cost_input.setEnabled(True)
                estimated = qty * line['unit_cost']
                cost_input.blockSignals(True)
                cost_input.setValue(estimated)
                cost_input.blockSignals(False)
                cost_input.setEnabled(False)
                fixed_total += estimated

        parts = []
        if fixed_total > 0:
            parts.append(f"<b>Fixed: ${fixed_total:.2f}</b>")
        if var_lines > 0:
            if var_total > 0:
                parts.append(
                    f"<span style='color:#FFA500'>"
                    f"Variable weight: ${var_total:.2f} "
                    f"({var_entered}/{var_lines} costs entered)</span>"
                )
            else:
                parts.append(
                    f"<span style='color:#f85149'>"
                    f"Variable weight: enter invoice totals above</span>"
                )
        grand = fixed_total + var_total
        parts.append(f"<b>Receipt Total: ${grand:.2f}</b>")
        self.total_label.setText("  |  ".join(parts))

    def _confirm(self):
        # Warn if variable weight lines missing cost
        missing = [
            line['description']
            for line, pack_qty, qty_input, cost_input, is_var_wt in self._inputs
            if is_var_wt and qty_input.value() > 0 and cost_input.value() == 0
        ]
        if missing:
            reply = QMessageBox.question(
                self, "Missing Invoice Costs",
                f"These variable weight lines have no invoice cost:\n"
                f"  • " + "\n  • ".join(missing) +
                f"\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        reply = QMessageBox.question(
            self, "Confirm Receipt", "Receive stock for all lines?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        all_received = True
        try:
         for line, pack_qty, qty_input, cost_input, is_var_wt in self._inputs:
            units_receiving = qty_input.value()
            if units_receiving > 0:
                # Convert units back to cartons for storage
                cartons_receiving = math.ceil(units_receiving / pack_qty) if pack_qty > 1 else units_receiving
                new_received_cartons = int(line['received_qty']) + cartons_receiving

                actual_cost = cost_input.value() if is_var_wt else None
                lines_model.receive(line['id'], new_received_cartons, actual_cost)

                # Stock adjustment in actual units received
                stock_model.adjust(
                    barcode=line['barcode'],
                    quantity=units_receiving,
                    movement_type=MOVE_RECEIPT,
                    reference=f"PO-{self.po_id}",
                )

                # Update cost price for variable weight from actual invoice
                if is_var_wt and actual_cost and actual_cost > 0:
                    from database.connection import get_connection
                    conn = get_connection()
                    conn.execute(
                        "UPDATE products SET cost_price=?, updated_at=CURRENT_TIMESTAMP "
                        "WHERE barcode=?",
                        (round(actual_cost / units_receiving, 4), line['barcode'])
                    )
                    conn.commit()
                    conn.close()

            # Check if fully received (compare in cartons)
            total_received_cartons = int(line['received_qty']) + (
                math.ceil(units_receiving / pack_qty) if pack_qty > 1 else units_receiving
            )
            if total_received_cartons < int(line['ordered_qty']):
                all_received = False

        except Exception as e:
            QMessageBox.critical(self, 'Receipt Error', f'An error occurred:\n\n{str(e)}\n\nNo stock has been updated.')
            import traceback; traceback.print_exc()
            return
        status = PO_STATUS_RECEIVED if all_received else PO_STATUS_PARTIAL
        po_model.update_status(self.po_id, status)
        if self.on_save:
            self.on_save()
        QMessageBox.information(self, 'Done', f'Stock received. PO status: {status}')
        self.close()
