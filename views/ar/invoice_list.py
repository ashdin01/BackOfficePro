from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QMessageBox
)
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QColor
import controllers.ar_controller as ar_ctrl
import config.styles as styles
from views.base_view import BaseView
from views.widgets.search_bar import SearchBar


STATUS_COLOURS = {
    'DRAFT':   '#555555',
    'SENT':    styles.CLR_ACCENT,
    'PARTIAL': '#e65100',
    'PAID':    styles.CLR_SUCCESS_DARK,
    'OVERDUE': '#b71c1c',
    'VOID':    '#424242',
}


class InvoiceList(BaseView):
    def __init__(self):
        super().__init__()
        self._open_wins = []
        self._build_ui()
        self.load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()

        self.search = SearchBar("Search customer or invoice…", interval=350)
        self.search.search_changed.connect(self._filter)
        top.addWidget(self.search)

        self.status_filter = QComboBox()
        self.status_filter.addItems(['All', 'DRAFT', 'SENT', 'PARTIAL', 'PAID', 'OVERDUE', 'VOID'])
        self.status_filter.currentTextChanged.connect(self._filter)
        top.addWidget(self.status_filter)

        btn_customers = QPushButton("&Customers")
        btn_customers.clicked.connect(self._open_customers)
        top.addWidget(btn_customers)

        btn_new = QPushButton("&New Invoice")
        btn_new.clicked.connect(self._new_invoice)
        top.addWidget(btn_new)

        btn_aged = QPushButton("Aged Debtors")
        btn_aged.clicked.connect(self._aged_debtors)
        top.addWidget(btn_aged)

        btn_recon = QPushButton("Reconcile…")
        btn_recon.clicked.connect(self._reconcile)
        top.addWidget(btn_recon)

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
        self.table.installEventFilter(self)
        layout.addWidget(self.table)

        self.status_lbl = QLabel("")
        layout.addWidget(self.status_lbl)

    def _load(self):
        ar_ctrl.refresh_overdue_statuses()
        self._all_rows = ar_ctrl.get_all_invoices()
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

    def _reconcile(self):
        from views.ar.recon_csv_mapper import ReconImportDialog
        dlg = ReconImportDialog(self)
        if dlg.exec():
            result = dlg.import_result()
            if result:
                from views.ar.recon_session import ReconSession
                w = ReconSession(batch=result['batch'], on_done=self._load)
                self._open_wins.append(w)
                w.show()

    def _open_customers(self):
        from views.ar.customer_list import CustomerList
        w = CustomerList()
        self._open_wins.append(w)
        w.show()

    def eventFilter(self, obj, event):
        if obj is self.table and event.type() == QEvent.Type.KeyPress:
            key  = event.key()
            mods = event.modifiers()
            if mods == Qt.KeyboardModifier.NoModifier:
                if key == Qt.Key.Key_C:
                    self._open_customers()
                    return True
                if key == Qt.Key.Key_N:
                    self._new_invoice()
                    return True
                if key == Qt.Key.Key_R:
                    self._reconcile()
                    return True
                if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                    self._open()
                    return True
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.load()
        self.table.setFocus()
