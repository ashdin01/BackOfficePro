from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import models.product as product_model


class ProductList(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by description or barcode...")
        self.search_input.textChanged.connect(self._search)
        # Pressing Enter in search box moves focus to table
        self.search_input.returnPressed.connect(self._focus_table)
        search_row.addWidget(self.search_input)

        btn_add = QPushButton("&Add Product")
        btn_add.clicked.connect(self._add)
        search_row.addWidget(btn_add)
        layout.addLayout(search_row)

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
        # Enter key on table opens the item
        self.table.keyPressEvent = self._table_key_press
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)

        # Hotkeys
        QShortcut(QKeySequence("N"), self, self._add)
        QShortcut(QKeySequence("/"), self, self._focus_search)

    def _table_key_press(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._edit()
        else:
            # Pass all other keys to default handler
            QTableWidget.keyPressEvent(self.table, event)

    def _focus_table(self):
        self.table.setFocus()
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

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
