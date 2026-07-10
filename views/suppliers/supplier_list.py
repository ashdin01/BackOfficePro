from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView
)
from PyQt6.QtCore import Qt
from utils.keyboard_mixin import KeyboardMixin
from views.widgets.search_bar import SearchBar
from views.base_view import BaseView
import controllers.supplier_controller as supplier_ctrl
from utils.text_search import matches_all_words


class SupplierList(KeyboardMixin, BaseView):
    def __init__(self, current_user=None):
        super().__init__()
        self._current_user = current_user or {}
        self._open_wins = []
        self._build_ui()
        self.load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = SearchBar("Search suppliers…", interval=500)
        self.search.search_changed.connect(lambda: self._search(self.search.text()))
        top.addWidget(self.search)
        btn_add = QPushButton("&Add Supplier")
        btn_add.clicked.connect(self._add)
        top.addWidget(btn_add)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Code", "Name", "Phone", "Rep Name", "Rep Phone", "Order Min", "Active"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        self.search.returnPressed.connect(self.table.setFocus)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.setup_keyboard(table=self.table)

    def _load(self, rows=None):
        if rows is None:
            rows = supplier_ctrl.get_all(active_only=False)
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row['code']))
            self.table.setItem(r, 1, QTableWidgetItem(row['name']))
            self.table.setItem(r, 2, QTableWidgetItem(row['phone'] or ''))
            self.table.setItem(r, 3, QTableWidgetItem(row['rep_name'] if 'rep_name' in row.keys() else ''))
            self.table.setItem(r, 4, QTableWidgetItem(row['rep_phone'] if 'rep_phone' in row.keys() else ''))
            order_min = row['order_minimum'] if 'order_minimum' in row.keys() else 0
            min_item = QTableWidgetItem(f"${order_min:.2f}" if order_min else "")
            min_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 5, min_item)
            active = QTableWidgetItem("Yes" if row['active'] else "No")
            active.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 6, active)
            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])
        self.status.setText(f"{self.table.rowCount()} suppliers")

    def _search(self, term):
        all_rows = supplier_ctrl.get_all(active_only=False)
        filtered = [r for r in all_rows if matches_all_words(term, r['name'], r['code'])]
        self._load(filtered)

    def _open_win(self, win):
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.show()
        win.raise_()
        win.activateWindow()
        def _alive(w):
            try:
                w.isVisible()
                return True
            except RuntimeError:
                return False
        self._open_wins = [w for w in self._open_wins if _alive(w)]
        self._open_wins.append(win)

    def _add(self):
        from views.suppliers.supplier_edit import SupplierEdit
        self._open_win(SupplierEdit(on_save=self._load, current_user=self._current_user))

    def _edit(self, index=None):
        row = self.table.currentRow()
        if row < 0:
            return
        supplier_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        from views.suppliers.supplier_edit import SupplierEdit
        self._open_win(SupplierEdit(supplier_id=supplier_id, on_save=self._load,
                                    current_user=self._current_user))
