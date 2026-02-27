from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView
)
import models.purchase_order as po_model
import models.po_lines as lines_model


class POHistory(QWidget):
    def __init__(self, po_id):
        super().__init__()
        self.po_id = po_id
        self.setMinimumSize(700, 400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        po = po_model.get_by_id(self.po_id)
        self.setWindowTitle(f"PO History: {po['po_number']}")

        layout.addWidget(QLabel(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — "
            f"Status: <b>{po['status']}</b>"
        ))

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Ordered", "Received", "Unit Cost"
        ])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        lines = lines_model.get_by_po(self.po_id)
        for line in lines:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(line['barcode']))
            table.setItem(r, 1, QTableWidgetItem(line['description']))
            table.setItem(r, 2, QTableWidgetItem(str(int(line['ordered_qty']))))
            table.setItem(r, 3, QTableWidgetItem(str(int(line['received_qty']))))
            table.setItem(r, 4, QTableWidgetItem(f"${line['unit_cost']:.2f}"))

        layout.addWidget(table)
