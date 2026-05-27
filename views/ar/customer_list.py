from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView
)
from PyQt6.QtCore import Qt
import controllers.ar_controller as ar_ctrl
from views.ar.customer_edit import CustomerEdit
from views.base_view import BaseView
from views.widgets.search_bar import SearchBar


class CustomerList(BaseView):
    def __init__(self):
        super().__init__()
        self._open_wins = []
        self._build_ui()
        self.load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()

        self.search = SearchBar("Search customers…", interval=350)
        self.search.search_changed.connect(self._filter)
        top.addWidget(self.search)

        self.chk_inactive = QPushButton("Show Inactive")
        self.chk_inactive.setCheckable(True)
        self.chk_inactive.toggled.connect(self._load)
        top.addWidget(self.chk_inactive)

        btn_add = QPushButton("&Add Customer")
        btn_add.clicked.connect(self._add)
        top.addWidget(btn_add)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Code", "Name", "ABN", "Phone", "Email", "Terms (days)", "Active"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        self.search.returnPressed.connect(self.table.setFocus)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)

    def _load(self, *_):
        active_only = not self.chk_inactive.isChecked()
        self._all_rows = ar_ctrl.get_all_customers(active_only=active_only)
        self._render(self._all_rows)

    def _filter(self):
        term = self.search.text().strip().lower()
        if not term:
            self._render(self._all_rows)
            return
        filtered = [r for r in self._all_rows
                    if term in (r['name'] or '').lower()
                    or term in (r['code'] or '').lower()
                    or term in (r['email'] or '').lower()]
        self._render(filtered)

    def _render(self, rows):
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [
                r['code'], r['name'], r['abn'] or '', r['phone'] or '',
                r['email'] or '', str(r['payment_terms_days']),
                'Yes' if r['active'] else 'No',
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, r['id'])
                self.table.setItem(i, j, item)
        self.status.setText(f"{len(rows)} customer(s)")

    def _add(self):
        w = CustomerEdit(customer_id=None, on_saved=self._load)
        self._open_wins.append(w)
        w.show()

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        cid = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        w = CustomerEdit(customer_id=cid, on_saved=self._load)
        self._open_wins.append(w)
        w.show()

    def showEvent(self, event):
        super().showEvent(event)
        self.load()
