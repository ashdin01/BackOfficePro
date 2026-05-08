"""
Credit/Return order close screen.
Confirms quantities being returned, adjusts SOH down, sets status CLOSED.
"""
import math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpinBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import models.purchase_order as po_model
import models.po_lines as lines_model
import controllers.purchase_order_controller as po_ctrl


class CreditClose(QWidget):
    def __init__(self, po_id, on_save=None):
        super().__init__()
        self.po_id   = po_id
        self.on_save = on_save
        self._inputs = []   # (line_row, qty_spinbox)
        self.setMinimumSize(820, 500)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.header = QLabel("")
        self.header.setStyleSheet("font-size:13px; font-weight:bold;")
        layout.addWidget(self.header)

        info = QLabel(
            "Confirm the quantities being returned below.  "
            "Stock on hand will be reduced when you close the return."
        )
        info.setStyleSheet("color:#8b949e; font-size:11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#2a3a4a;")
        layout.addWidget(sep)

        # ── Line items table ──────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Description", "Pack", "Return Qty (cartons)", "Unit Cost", "Credit Value"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 110)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # ── Credit total ──────────────────────────────────────────────
        self.total_label = QLabel("")
        self.total_label.setStyleSheet("font-size:12px; padding:4px 0;")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)

        # ── Buttons ───────────────────────────────────────────────────
        btns = QHBoxLayout()
        btns.setSpacing(8)

        fill_btn = QPushButton("Fill All Returns")
        fill_btn.setFixedHeight(34)
        fill_btn.setStyleSheet(
            "QPushButton{background:#1e2a38;color:#8b949e;"
            "border:1px solid #2a3a4a;border-radius:4px;padding:0 12px;}"
            "QPushButton:hover{color:#e6edf3;border-color:#8b949e;}")
        fill_btn.clicked.connect(self._fill_all)

        confirm_btn = QPushButton("✓  Confirm & Close Return  [Enter]")
        confirm_btn.setFixedHeight(34)
        confirm_btn.setStyleSheet(
            "QPushButton{background:#b71c1c;color:white;border:none;"
            "border-radius:4px;padding:0 16px;font-weight:bold;}"
            "QPushButton:hover{background:#c62828;}")
        confirm_btn.clicked.connect(self._confirm)

        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#8b949e;"
            "border:1px solid #2a3a4a;border-radius:4px;padding:0 12px;}"
            "QPushButton:hover{background:#1e2a38;color:#e6edf3;}")
        cancel_btn.clicked.connect(self.close)

        btns.addWidget(fill_btn)
        btns.addStretch()
        btns.addWidget(confirm_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        QShortcut(QKeySequence("Return"), self, self._confirm)
        QShortcut(QKeySequence("Enter"),  self, self._confirm)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        po    = po_model.get_by_id(self.po_id)
        lines = lines_model.get_by_po(self.po_id)

        self.setWindowTitle(f"Close Credit Return: {po['po_number']}")
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — Credit / Return"
        )

        self._po_number = po['po_number']
        self._inputs    = []
        self.table.setRowCount(0)

        for line in lines:
            ordered = int(line['ordered_qty'] or 0)
            pack_qty  = int(line['pack_qty'] or 1)
            pack_unit = 'EA'
            unit_cost = float(line['unit_cost'] or 0)

            r = self.table.rowCount()
            self.table.insertRow(r)

            desc_item = QTableWidgetItem(line['description'])
            desc_item.setData(Qt.ItemDataRole.UserRole, line['id'])
            self.table.setItem(r, 0, desc_item)

            pack_str = f"{pack_qty}×EA" if pack_qty > 1 else "EA"
            self.table.setItem(r, 1, QTableWidgetItem(pack_str))

            qty_spin = QSpinBox()
            qty_spin.setMinimum(0)
            qty_spin.setMaximum(ordered)
            qty_spin.setValue(ordered)
            qty_spin.setFixedHeight(28)
            qty_spin.valueChanged.connect(self._update_total)
            self.table.setCellWidget(r, 2, qty_spin)

            cost_item = QTableWidgetItem(f"${unit_cost:.2f}")
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 3, cost_item)

            total_item = QTableWidgetItem("")
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 4, total_item)

            self._inputs.append({
                'line':      line,
                'pack_qty':  pack_qty,
                'unit_cost': unit_cost,
                'qty_spin':  qty_spin,
                'total_col': 4,
                'row':       r,
            })

        self.table.setRowHeight(r, 32) if lines else None
        self._update_total()

    def _update_total(self):
        grand = 0.0
        for entry in self._inputs:
            cartons   = entry['qty_spin'].value()
            units     = cartons * entry['pack_qty']
            line_val  = units * entry['unit_cost']
            grand    += line_val
            item = self.table.item(entry['row'], entry['total_col'])
            if item:
                item.setText(f"${line_val:.2f}")
        self.total_label.setText(
            f"Credit Value (ex. GST):  <b>${grand:.2f}</b>"
        )

    def _fill_all(self):
        for entry in self._inputs:
            entry['qty_spin'].setValue(entry['qty_spin'].maximum())

    def _confirm(self):
        po = po_model.get_by_id(self.po_id)
        if po['status'] not in ('DRAFT', 'SENT'):
            QMessageBox.warning(
                self, "Cannot Close",
                f"{po['po_number']} has status '{po['status']}' and cannot be closed."
            )
            return

        total_qty = sum(e['qty_spin'].value() for e in self._inputs)
        if total_qty == 0:
            QMessageBox.warning(
                self, "No Quantities",
                "All return quantities are zero. Enter at least one quantity to close."
            )
            return

        reply = QMessageBox.question(
            self, "Confirm Close Return",
            f"Close credit return {po['po_number']}?\n\n"
            f"Stock on hand will be reduced for all lines with quantity > 0.\n\n"
            f"This cannot be undone."
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        line_receipts = []
        for entry in self._inputs:
            cartons = entry['qty_spin'].value()
            if cartons <= 0:
                continue
            qty_units = cartons * entry['pack_qty']
            line_receipts.append({
                'line_id':       entry['line']['id'],
                'barcode':       entry['line']['barcode'],
                'return_cartons': cartons,
                'qty_units':     qty_units,
            })

        try:
            po_ctrl.close_credit_atomic(self.po_id, self._po_number, line_receipts)
        except Exception as exc:
            QMessageBox.critical(
                self, "Close Failed",
                f"An error occurred — no changes were saved.\n\n{exc}"
            )
            return

        if self.on_save:
            self.on_save()
        QMessageBox.information(
            self, "Return Closed",
            f"Credit return {po['po_number']} closed.\nStock has been adjusted."
        )
        self.close()
