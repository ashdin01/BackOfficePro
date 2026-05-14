from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit,
    QComboBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import models.ar_invoice as invoice_model
import controllers.ar_controller as ar_ctrl
from database.connection import get_connection


class CreditNoteDetail(QWidget):
    def __init__(self, customer_id, linked_invoice_id=None, cn_id=None):
        super().__init__()
        self._customer_id       = customer_id
        self._linked_invoice_id = linked_invoice_id
        self._cn_id             = cn_id
        self.setWindowFlags(Qt.WindowType.Window)
        self.setMinimumSize(700, 500)
        self.setWindowTitle("Credit Note")
        self._build_ui()
        if cn_id:
            self._load()
        elif linked_invoice_id:
            self._prefill_from_invoice()

    def _build_ui(self):
        root = QVBoxLayout(self)

        info = QHBoxLayout()
        self.lbl_cn = QLabel("New Credit Note")
        self.lbl_cn.setStyleSheet("font-size:14px; font-weight:bold;")
        info.addWidget(self.lbl_cn)
        info.addStretch()
        self.btn_issue = QPushButton("Issue Credit Note")
        self.btn_issue.clicked.connect(self._issue)
        info.addWidget(self.btn_issue)
        root.addLayout(info)

        form = QFormLayout()
        self.lbl_inv = QLabel("—")
        form.addRow("Linked Invoice:", self.lbl_inv)
        self.reason = QTextEdit(); self.reason.setMaximumHeight(70)
        form.addRow("Reason:", self.reason)
        root.addLayout(form)

        root.addWidget(QLabel("Lines (copied from invoice if linked):"))

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Description", "Qty", "Unit Price", "GST", "Total"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)

        totals = QHBoxLayout()
        totals.addStretch()
        self.lbl_total = QLabel("Total Credit: $0.00")
        self.lbl_total.setStyleSheet("font-weight:bold; font-size:13px;")
        totals.addWidget(self.lbl_total)
        root.addLayout(totals)

    def _prefill_from_invoice(self):
        inv = invoice_model.get_by_id(self._linked_invoice_id)
        if not inv:
            return
        self.lbl_inv.setText(f"{inv['invoice_number']} ({inv['invoice_date']})")
        lines = invoice_model.get_lines(self._linked_invoice_id)
        self._render_lines(lines)
        total = sum(float(ln['line_total']) for ln in lines)
        self.lbl_total.setText(f"Total Credit: ${total:.2f}")

    def _render_lines(self, lines):
        self.table.setRowCount(len(lines))
        for i, ln in enumerate(lines):
            for j, v in enumerate([
                ln['description'], f"{ln['quantity']:g}",
                f"${ln['unit_price']:.2f}", f"${ln['line_gst']:.2f}",
                f"${ln['line_total']:.2f}",
            ]):
                self.table.setItem(i, j, QTableWidgetItem(str(v)))

    def _issue(self):
        reason = self.reason.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Validation", "Please enter a reason.")
            return
        try:
            cn_id, cn_num = ar_ctrl.create_credit_note(
                customer_id=self._customer_id,
                reason=reason,
                invoice_id=self._linked_invoice_id,
            )
            self._cn_id = cn_id
            self.lbl_cn.setText(f"Credit Note {cn_num}")
            self.btn_issue.setEnabled(False)
            QMessageBox.information(self, "Credit Note", f"Issued: {cn_num}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _load(self):
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM ar_credit_notes WHERE id=?", (self._cn_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return
        self.lbl_cn.setText(f"Credit Note {row['credit_note_number']}")
        self.reason.setPlainText(row['reason'] or '')
        if row['invoice_id']:
            self._linked_invoice_id = row['invoice_id']
            self._prefill_from_invoice()
