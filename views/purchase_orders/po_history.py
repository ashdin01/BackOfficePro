from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from utils.error_dialog import show_error
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.product as product_model


class POHistory(QWidget):
    def __init__(self, po_id, on_close=None):
        super().__init__()
        self.po_id = po_id
        self.on_close = on_close
        self.setMinimumSize(900, 500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        po = po_model.get_by_id(self.po_id)
        self.setWindowTitle(f"PO History: {po['po_number']}")

        # Header
        status_color = {
            'RECEIVED': '#4CAF50',
            'CANCELLED': '#f44336',
            'REVERSED': '#9C27B0',
            'PARTIAL': '#FF9800',
        }.get(po['status'], '#8b949e')

        self.header = QLabel(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — "
            f"Status: <b style='color:{status_color}'>{po['status']}</b>"
        )
        self.header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.header)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Pack Size", "Ordered", "Received", "Unit Cost"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self._load_lines(po)

        # Buttons
        btns = QHBoxLayout()

        if po['status'] in ('RECEIVED', 'PARTIAL'):
            btn_reverse = QPushButton("↩ Reverse PO")
            btn_reverse.setFixedHeight(35)
            btn_reverse.setStyleSheet(
                "QPushButton{background:#6a1b9a;color:white;font-weight:bold;"
                "border:none;border-radius:4px;padding:0 16px;}"
                "QPushButton:hover{background:#7b1fa2;}"
            )
            btn_reverse.setToolTip(
                "Reverse this PO — reduces stock on hand by all received quantities"
            )
            btn_reverse.clicked.connect(self._reverse)
            btns.addWidget(btn_reverse)

        btns.addStretch()
        btn_close = QPushButton("Close  [Esc]")
        btn_close.setFixedHeight(35)
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load_lines(self, po=None):
        if po is None:
            po = po_model.get_by_id(self.po_id)
        self.table.setRowCount(0)
        lines = lines_model.get_by_po(self.po_id)
        for line in lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            product = product_model.get_by_barcode(line['barcode'])
            pack_qty  = int(product['pack_qty']) if product and product['pack_qty'] else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
            pack_str  = f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit

            self.table.setItem(r, 0, QTableWidgetItem(line['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(line['description']))
            self.table.setItem(r, 2, QTableWidgetItem(pack_str))
            self.table.setItem(r, 3, QTableWidgetItem(str(int(line['ordered_qty']))))
            recv_item = QTableWidgetItem(str(int(line['received_qty'])))
            recv_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if int(line['received_qty']) > 0:
                recv_item.setForeground(QColor('#4CAF50'))
            self.table.setItem(r, 4, recv_item)
            self.table.setItem(r, 5, QTableWidgetItem(f"${line['unit_cost']:.2f}"))

    def _reverse(self):
        po = po_model.get_by_id(self.po_id)
        lines = lines_model.get_by_po(self.po_id)

        # Build summary of what will be reversed
        summary_lines = []
        for line in lines:
            received = int(line['received_qty'] or 0)
            if received > 0:
                product = product_model.get_by_barcode(line['barcode'])
                pack_qty = int(product['pack_qty']) if product and product['pack_qty'] else 1
                units = received * pack_qty
                summary_lines.append(f"  • {line['description']}: -{units} units")

        if not summary_lines:
            QMessageBox.information(self, "Nothing to Reverse",
                "No received quantities found on this PO.")
            return

        summary = "\n".join(summary_lines[:10])
        if len(summary_lines) > 10:
            summary += f"\n  ... and {len(summary_lines) - 10} more lines"

        reply = QMessageBox.warning(
            self, "Confirm PO Reversal",
            f"This will REVERSE {po['po_number']} — {po['supplier_name']}.\n\n"
            f"The following stock will be REMOVED from inventory:\n\n"
            f"{summary}\n\n"
            f"This action cannot be undone. The PO will be marked REVERSED.\n\n"
            f"Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            po_model.reverse(self.po_id)
            QMessageBox.information(
                self, "PO Reversed",
                f"{po['po_number']} has been reversed.\n"
                f"Stock on hand has been reduced accordingly.\n"
                f"Movement history has been updated."
            )
            if self.on_close:
                self.on_close()
            self.close()
        except Exception as e:
            show_error(self, "Could not reverse purchase order.", e, title="Reversal Failed")
