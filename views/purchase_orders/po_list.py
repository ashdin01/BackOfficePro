from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QComboBox
)
from PyQt6.QtCore import Qt
import models.purchase_order as po_model
from config.constants import PO_STATUSES


class POList(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("All", None)
        for s in PO_STATUSES:
            self.status_filter.addItem(s, s)
        self.status_filter.currentIndexChanged.connect(self._load)
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self.status_filter)
        top.addStretch()
        btn_new = QPushButton("+ New Purchase Order")
        btn_new.clicked.connect(self._create)
        top.addWidget(btn_new)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "PO Number", "Supplier", "Status", "Delivery Date", "Created", "Notes"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._open)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)

    def _load(self):
        status = self.status_filter.currentData()
        rows = po_model.get_all(status=status)
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row['po_number']))
            self.table.setItem(r, 1, QTableWidgetItem(row['supplier_name']))
            self.table.setItem(r, 2, QTableWidgetItem(row['status']))
            self.table.setItem(r, 3, QTableWidgetItem(row['delivery_date'] or ''))
            self.table.setItem(r, 4, QTableWidgetItem(row['created_at'][:10]))
            self.table.setItem(r, 5, QTableWidgetItem(row['notes'] or ''))
            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])
        self.status.setText(f"{self.table.rowCount()} purchase orders")

    def _create(self):
        from views.purchase_orders.po_create import POCreate
        self.create_win = POCreate(on_save=self._load)
        self.create_win.show()

    def _open(self):
        row = self.table.currentRow()
        if row < 0:
            return
        po_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        status = self.table.item(row, 2).text()
        if status == 'RECEIVED' or status == 'CANCELLED':
            from views.purchase_orders.po_history import POHistory
            self.detail_win = POHistory(po_id=po_id)
        elif status == 'SENT' or status == 'PARTIAL':
            from views.purchase_orders.po_receive import POReceive
            self.detail_win = POReceive(po_id=po_id, on_save=self._load)
        else:
            from views.purchase_orders.po_detail import PODetail
            self.detail_win = PODetail(po_id=po_id, on_save=self._load)
        self.detail_win.show()
