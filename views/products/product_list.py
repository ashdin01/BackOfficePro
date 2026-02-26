from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QLabel, QHeaderView
)
from PyQt6.QtCore import Qt
import models.product as product_model


class ProductList(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Products")
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Search bar
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by description or barcode...")
        self.search_input.textChanged.connect(self._search)
        search_row.addWidget(self.search_input)

        btn_add = QPushButton("+ Add Product")
        btn_add.clicked.connect(self._add)
        search_row.addWidget(btn_add)
        layout.addLayout(search_row)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department", "Supplier",
            "Unit", "Sell Price", "Cost Price"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        # Status
        self.status = QLabel("")
        layout.addWidget(self.status)

    def _load(self, rows=None):
        if rows is None:
            rows = product_model.get_all()
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(row['description']))
            self.table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))
            self.table.setItem(r, 3, QTableWidgetItem(row['supplier_name'] or ''))
            self.table.setItem(r, 4, QTableWidgetItem(row['unit'] or ''))
            self.table.setItem(r, 5, QTableWidgetItem(f"${row['sell_price']:.2f}"))
            self.table.setItem(r, 6, QTableWidgetItem(f"${row['cost_price']:.2f}"))
        self.status.setText(f"{self.table.rowCount()} products")

    def _search(self, term):
        if term.strip():
            self._load(product_model.search(term))
        else:
            self._load()

    def _add(self):
        from views.products.product_add import ProductAdd
        self.add_win = ProductAdd(on_save=self._load)
        self.add_win.show()

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        barcode = self.table.item(row, 0).text()
        from views.products.product_edit import ProductEdit
        self.edit_win = ProductEdit(barcode=barcode, on_save=self._load)
        self.edit_win.show()
