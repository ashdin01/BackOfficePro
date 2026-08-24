from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialogButtonBox, QMessageBox,
)
from PyQt6.QtCore import Qt
import controllers.purchase_order_controller as po_controller
from views.widgets.search_bar import SearchBar


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
        self.search_input = SearchBar(
            placeholder="Search barcode, description, brand, department or supplier SKU…"
        )
        self.search_input.search_changed.connect(
            lambda: self._search(self.search_input.text())
        )
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Supplier", "Barcode", "Description", "Supplier SKU", "Pack Size", "Cost Price"]
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 100)
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

        self.search_input.setFocus()
        self._search('')

    def _search(self, term):
        """Multi-word AND search — same logic as the main Products window
        (models.product.search), scoped to items linked to this PO's
        supplier. An empty term returns the full supplier item list."""
        rows = po_controller.get_items_for_supplier(self.supplier_id, term)
        self._populate([dict(r) for r in rows])

    def _populate(self, rows):
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            pack_str = f"{r['pack_qty']} × {r['pack_unit']}"
            self.table.setItem(row, 0, QTableWidgetItem(r['supplier_name']))
            self.table.setItem(row, 1, QTableWidgetItem(r['barcode']))
            self.table.setItem(row, 2, QTableWidgetItem(r['description']))
            self.table.setItem(row, 3, QTableWidgetItem(r.get('supplier_sku') or ''))
            self.table.setItem(row, 4, QTableWidgetItem(pack_str))
            cost_item = QTableWidgetItem(f"${r['cost_price']:.2f}")
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 5, cost_item)

    def _on_accept(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No selection", "Please select an item first.")
            return
        self.selected = {
            "barcode": self.table.item(row, 1).text(),
            "cost_price": float(self.table.item(row, 5).text().replace("$", "") or 0),
        }
        self.accept()
