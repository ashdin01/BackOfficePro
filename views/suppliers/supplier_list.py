from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QLineEdit
)
from PyQt6.QtCore import Qt
from utils.keyboard_mixin import KeyboardMixin
import models.supplier as supplier_model


class SupplierList(KeyboardMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search suppliers...")
        self.search.textChanged.connect(self._search)
        self.search.returnPressed.connect(lambda: self.table.setFocus())
        top.addWidget(self.search)
        btn_add = QPushButton("&Add Supplier")
        btn_add.clicked.connect(self._add)
        top.addWidget(btn_add)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Code", "Name", "Contact", "Phone", "Active"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.setup_keyboard(table=self.table)

    def _load(self, rows=None):
        if rows is None:
            rows = supplier_model.get_all(active_only=False)
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row['code']))
            self.table.setItem(r, 1, QTableWidgetItem(row['name']))
            self.table.setItem(r, 2, QTableWidgetItem(row['contact_name'] or ''))
            self.table.setItem(r, 3, QTableWidgetItem(row['phone'] or ''))
            active = QTableWidgetItem("Yes" if row['active'] else "No")
            active.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, active)
            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])
        self.status.setText(f"{self.table.rowCount()} suppliers")

    def _search(self, term):
        term = term.lower()
        all_rows = supplier_model.get_all(active_only=False)
        filtered = [r for r in all_rows if term in r['name'].lower() or term in r['code'].lower()]
        self._load(filtered)

    def _add(self):
        from views.suppliers.supplier_edit import SupplierEdit
        self.edit_win = SupplierEdit(on_save=self._load)
        self.edit_win.show()

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        supplier_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        from views.suppliers.supplier_edit import SupplierEdit
        self.edit_win = SupplierEdit(supplier_id=supplier_id, on_save=self._load)
        self.edit_win.show()
