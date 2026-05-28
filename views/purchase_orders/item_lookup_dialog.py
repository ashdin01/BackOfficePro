from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialogButtonBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
import controllers.purchase_order_controller as po_controller


class ItemLookupDialog(QDialog):
    def __init__(self, parent=None, supplier_id=None):
        super().__init__(parent)
        self.supplier_id = supplier_id
        self.setWindowTitle("Item Lookup — This Supplier" if supplier_id else "Item Lookup")
        self.setMinimumSize(860, 540)
        self.selected = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by supplier, barcode or description...")
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(500)
        self._filter_timer.timeout.connect(lambda: self._filter(self.search_input.text()))
        self.search_input.textChanged.connect(lambda _: self._filter_timer.start())
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Supplier", "Barcode", "Description", "Pack Size", "Cost Price"]
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 100)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_accept)
        layout.addWidget(self.table)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._load_products()

    def _load_products(self):
        rows = po_controller.get_items_for_supplier(self.supplier_id)
        self._all_rows = [dict(r) for r in rows]
        self._populate(self._all_rows)

    def _populate(self, rows):
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            pack_str = f"{r['pack_qty']} × {r['pack_unit']}"
            self.table.setItem(row, 0, QTableWidgetItem(r['supplier_name']))
            self.table.setItem(row, 1, QTableWidgetItem(r['barcode']))
            self.table.setItem(row, 2, QTableWidgetItem(r['description']))
            self.table.setItem(row, 3, QTableWidgetItem(pack_str))
            cost_item = QTableWidgetItem(f"${r['cost_price']:.2f}")
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, cost_item)

    def _filter(self, text):
        text = text.lower()
        filtered = [
            r for r in self._all_rows
            if (text in r['supplier_name'].lower()
                or text in r['barcode'].lower()
                or text in r['description'].lower())
        ]
        self._populate(filtered)

    def _on_accept(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No selection", "Please select an item first.")
            return
        self.selected = {
            "barcode": self.table.item(row, 1).text(),
            "cost_price": float(self.table.item(row, 4).text().replace("$", "") or 0),
        }
        self.accept()
