"""Bank reconciliation matching screen."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QMessageBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

import models.bank_recon as recon_model
import models.ar_invoice as invoice_model
import controllers.ar_controller as ar_ctrl

_GREEN  = QColor('#c8e6c9')
_YELLOW = QColor('#fff9c4')
_GREY   = QColor('#eeeeee')
_RED    = QColor('#ffcdd2')


class ReconSession(QWidget):
    def __init__(self, batch: str, on_done=None):
        super().__init__()
        self._batch   = batch
        self._on_done = on_done
        self._txns    = []
        self._invoices = []
        self.setWindowTitle(f"Reconcile — {batch}")
        self.resize(1200, 680)
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── summary bar ──────────────────────────────────────────────────────
        self.summary_lbl = QLabel("")
        bold = QFont(); bold.setBold(True)
        self.summary_lbl.setFont(bold)
        root.addWidget(self.summary_lbl)

        # ── splitter ─────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left — bank transactions
        left = QWidget()
        lv   = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 4, 0)
        lv.addWidget(QLabel("Bank Transactions"))
        self.txn_table = QTableWidget()
        self.txn_table.setColumnCount(4)
        self.txn_table.setHorizontalHeaderLabels(["Date", "Amount", "Description", "Status"])
        self.txn_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.txn_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.txn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.txn_table.setAlternatingRowColors(True)
        self.txn_table.selectionModel().selectionChanged.connect(self._on_txn_selected)
        lv.addWidget(self.txn_table)

        # Right — outstanding invoices
        right = QWidget()
        rv    = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.addWidget(QLabel("Open Invoices  (green = amount matches)"))
        self.inv_table = QTableWidget()
        self.inv_table.setColumnCount(6)
        self.inv_table.setHorizontalHeaderLabels(
            ["Invoice #", "Customer", "Date", "Due Date", "Total", "Owing"]
        )
        self.inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.inv_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inv_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.inv_table.setAlternatingRowColors(True)
        rv.addWidget(self.inv_table)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([560, 640])
        root.addWidget(splitter)

        # ── action bar ───────────────────────────────────────────────────────
        actions = QHBoxLayout()

        self.btn_match = QPushButton("⇔  Match Selected")
        self.btn_match.setEnabled(False)
        self.btn_match.clicked.connect(self._match)
        actions.addWidget(self.btn_match)

        self.btn_ignore = QPushButton("Ignore")
        self.btn_ignore.setEnabled(False)
        self.btn_ignore.clicked.connect(self._ignore)
        actions.addWidget(self.btn_ignore)

        self.btn_unmatch = QPushButton("Unmatch")
        self.btn_unmatch.setEnabled(False)
        self.btn_unmatch.clicked.connect(self._unmatch)
        actions.addWidget(self.btn_unmatch)

        actions.addStretch()

        self.btn_finish = QPushButton("Finish Reconciliation")
        self.btn_finish.clicked.connect(self._finish)
        actions.addWidget(self.btn_finish)

        root.addLayout(actions)

    # ── data loading ─────────────────────────────────────────────────────────

    def _load(self):
        self._txns    = recon_model.get_transactions(self._batch)
        ar_ctrl.refresh_overdue_statuses()
        self._invoices = [
            r for r in invoice_model.get_all()
            if r['status'] not in ('PAID', 'VOID', 'DRAFT')
        ]
        self._render_txns()
        self._render_invoices(highlight_amount=None)
        self._update_summary()

    def _render_txns(self):
        self.txn_table.setRowCount(len(self._txns))
        for i, t in enumerate(self._txns):
            status = t['status']
            vals   = [t['txn_date'], f"{float(t['amount']):+.2f}",
                      t['description'] or '', status]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, t['id'])
                if status == 'MATCHED':
                    item.setBackground(_GREEN)
                elif status == 'IGNORED':
                    item.setBackground(_GREY)
                elif float(t['amount']) < 0:
                    item.setBackground(_YELLOW)
                self.txn_table.setItem(i, j, item)
        self.txn_table.resizeColumnToContents(0)
        self.txn_table.resizeColumnToContents(1)
        self.txn_table.resizeColumnToContents(3)

    def _render_invoices(self, highlight_amount):
        self.inv_table.setRowCount(len(self._invoices))
        for i, inv in enumerate(self._invoices):
            owing  = round(float(inv['total']) - float(inv['amount_paid']), 2)
            match  = (highlight_amount is not None
                      and abs(owing - highlight_amount) <= 0.02)
            vals   = [
                inv['invoice_number'],
                inv['customer_name'],
                inv['invoice_date'],
                inv['due_date'],
                f"${float(inv['total']):.2f}",
                f"${owing:.2f}",
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, inv['id'])
                if match:
                    item.setBackground(_GREEN)
                elif inv['status'] == 'OVERDUE':
                    item.setBackground(_RED)
                self.inv_table.setItem(i, j, item)
        self.inv_table.resizeColumnToContents(0)
        self.inv_table.resizeColumnToContents(2)
        self.inv_table.resizeColumnToContents(3)
        self.inv_table.resizeColumnToContents(4)
        self.inv_table.resizeColumnToContents(5)

    def _update_summary(self):
        total     = len(self._txns)
        matched   = sum(1 for t in self._txns if t['status'] == 'MATCHED')
        ignored   = sum(1 for t in self._txns if t['status'] == 'IGNORED')
        unmatched = sum(1 for t in self._txns if t['status'] == 'UNMATCHED')
        self.summary_lbl.setText(
            f"Batch: {self._batch}   |   "
            f"Total: {total}   Matched: {matched}   "
            f"Ignored: {ignored}   Unmatched: {unmatched}"
        )

    # ── selection ────────────────────────────────────────────────────────────

    def _selected_txn(self):
        row = self.txn_table.currentRow()
        if row < 0 or row >= len(self._txns):
            return None
        return self._txns[row]

    def _selected_inv_id(self):
        row = self.inv_table.currentRow()
        if row < 0:
            return None
        item = self.inv_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_txn_selected(self):
        t = self._selected_txn()
        if t is None:
            self.btn_match.setEnabled(False)
            self.btn_ignore.setEnabled(False)
            self.btn_unmatch.setEnabled(False)
            self._render_invoices(highlight_amount=None)
            return

        status = t['status']
        amount = float(t['amount'])

        self.btn_ignore.setEnabled(status == 'UNMATCHED')
        self.btn_unmatch.setEnabled(status in ('MATCHED', 'IGNORED'))
        # Match requires a positive credit and UNMATCHED status
        self.btn_match.setEnabled(status == 'UNMATCHED' and amount > 0)

        # Highlight invoices whose owing ≈ this amount
        self._render_invoices(highlight_amount=amount if amount > 0 else None)

    # ── actions ──────────────────────────────────────────────────────────────

    def _match(self):
        t = self._selected_txn()
        if not t or t['status'] != 'UNMATCHED':
            return
        inv_id = self._selected_inv_id()
        if not inv_id:
            QMessageBox.information(self, "Match", "Select an invoice on the right first.")
            return

        inv = invoice_model.get_by_id(inv_id)
        if not inv:
            return
        owing  = round(float(inv['total']) - float(inv['amount_paid']), 2)
        amount = round(float(t['amount']), 2)

        if abs(owing - amount) > 0.02:
            reply = QMessageBox.question(
                self, "Amount Mismatch",
                f"Bank amount is ${amount:.2f} but invoice owing is ${owing:.2f}.\n"
                f"Record partial payment of ${amount:.2f}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            payment_id = ar_ctrl.record_payment(
                invoice_id   = inv_id,
                amount       = amount,
                payment_date = t['txn_date'],
                method       = 'EFT',
                reference    = t.get('reference') or '',
                notes        = f"Bank recon {self._batch}",
            )
            recon_model.set_matched(t['id'], inv_id, payment_id)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        self._load()

    def _ignore(self):
        t = self._selected_txn()
        if not t or t['status'] != 'UNMATCHED':
            return
        recon_model.set_ignored(t['id'])
        self._load()

    def _unmatch(self):
        t = self._selected_txn()
        if not t or t['status'] not in ('MATCHED', 'IGNORED'):
            return
        recon_model.unmatch_transaction(t['id'])
        self._load()

    def _finish(self):
        unmatched = sum(1 for t in self._txns if t['status'] == 'UNMATCHED')
        if unmatched:
            reply = QMessageBox.question(
                self, "Unmatched Transactions",
                f"{unmatched} transaction(s) are still unmatched.\n"
                "Close the reconciliation session anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if self._on_done:
            self._on_done()
        self.close()
