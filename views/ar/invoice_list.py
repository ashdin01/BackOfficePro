from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QLineEdit,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
import models.ar_invoice as invoice_model
import controllers.ar_controller as ar_ctrl


STATUS_COLOURS = {
    'DRAFT':   '#555555',
    'SENT':    '#1565c0',
    'PARTIAL': '#e65100',
    'PAID':    '#2e7d32',
    'OVERDUE': '#b71c1c',
    'VOID':    '#424242',
}


class InvoiceList(QWidget):
    def __init__(self):
        super().__init__()
        self._open_wins = []
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search customer or invoice…")
        self._timer = QTimer(); self._timer.setSingleShot(True); self._timer.setInterval(350)
        self._timer.timeout.connect(self._filter)
        self.search.textChanged.connect(lambda _: self._timer.start())
        top.addWidget(self.search)

        self.status_filter = QComboBox()
        self.status_filter.addItems(['All', 'DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE', 'VOID'])
        self.status_filter.currentTextChanged.connect(self._filter)
        top.addWidget(self.status_filter)

        btn_new = QPushButton("&New Invoice")
        btn_new.clicked.connect(self._new_invoice)
        top.addWidget(btn_new)

        btn_aged = QPushButton("Aged Debtors")
        btn_aged.clicked.connect(self._aged_debtors)
        top.addWidget(btn_aged)

        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Invoice #", "Customer", "Date", "Due Date",
            "Total", "Paid", "Balance", "Status",
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._open)
        layout.addWidget(self.table)

        self.status_lbl = QLabel("")
        layout.addWidget(self.status_lbl)

    def _load(self):
        ar_ctrl.refresh_overdue_statuses()
        self._all_rows = invoice_model.get_all()
        self._filter()

    def _filter(self):
        term   = self.search.text().strip().lower()
        status = self.status_filter.currentText()
        rows   = self._all_rows
        if status != 'All':
            rows = [r for r in rows if r['status'] == status]
        if term:
            rows = [r for r in rows
                    if term in (r['customer_name'] or '').lower()
                    or term in (r['invoice_number'] or '').lower()]
        self._render(rows)

    def _render(self, rows):
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            balance = round(float(r['total']) - float(r['amount_paid']), 2)
            vals = [
                r['invoice_number'],
                r['customer_name'],
                r['invoice_date'],
                r['due_date'],
                f"${float(r['total']):.2f}",
                f"${float(r['amount_paid']):.2f}",
                f"${balance:.2f}",
                r['status'],
            ]
            colour = STATUS_COLOURS.get(r['status'], '#ffffff')
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, r['id'])
                if j == 7:
                    item.setForeground(QColor(colour))
                self.table.setItem(i, j, item)
        total_outstanding = sum(
            round(float(r['total']) - float(r['amount_paid']), 2)
            for r in rows if r['status'] not in ('PAID', 'VOID')
        )
        self.status_lbl.setText(
            f"{len(rows)} invoice(s)  |  Outstanding: ${total_outstanding:.2f}"
        )

    def _new_invoice(self):
        from views.ar.invoice_detail import InvoiceDetail
        w = InvoiceDetail(invoice_id=None, on_saved=self._load)
        self._open_wins.append(w)
        w.show()

    def _open(self):
        row = self.table.currentRow()
        if row < 0:
            return
        inv_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        from views.ar.invoice_detail import InvoiceDetail
        w = InvoiceDetail(invoice_id=inv_id, on_saved=self._load)
        self._open_wins.append(w)
        w.show()

    def _aged_debtors(self):
        from views.ar.aged_debtors import AgedDebtorsReport
        w = AgedDebtorsReport()
        self._open_wins.append(w)
        w.show()

    def showEvent(self, event):
        super().showEvent(event)
        self._load()
