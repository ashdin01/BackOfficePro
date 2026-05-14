from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import controllers.ar_controller as ar_ctrl


class AgedDebtorsReport(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Window)
        self.setMinimumSize(900, 500)
        self.setWindowTitle("Aged Debtors")
        self._open_wins = []
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Aged Debtors Report</b>"))
        top.addStretch()
        btn_stmt = QPushButton("Generate Statement…")
        btn_stmt.clicked.connect(self._statement)
        top.addWidget(btn_stmt)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._load)
        top.addWidget(btn_refresh)
        root.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Customer", "Current", "1–30 Days", "31–60 Days", "60+ Days", "Total", ""
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)

        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet("font-weight:bold; font-size:12px;")
        root.addWidget(self.lbl_total)

    def _load(self):
        ar_ctrl.refresh_overdue_statuses()
        rows = ar_ctrl.get_aged_debtors()
        self.table.setRowCount(len(rows))
        grand_total = 0.0
        for i, r in enumerate(rows):
            vals = [
                r['customer_name'],
                f"${r['current']:.2f}",
                f"${r['days_30']:.2f}",
                f"${r['days_60']:.2f}",
                f"${r['days_90plus']:.2f}",
                f"${r['total']:.2f}",
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, r['customer_id'])
                if j > 0 and j < 6:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if j == 4 and r['days_90plus'] > 0:
                    item.setForeground(QColor('#b71c1c'))
                self.table.setItem(i, j, item)
            grand_total += r['total']

        self.lbl_total.setText(f"Total Outstanding: ${grand_total:.2f}")

    def _statement(self):
        row = self.table.currentRow()
        cid = None
        if row >= 0:
            item = self.table.item(row, 0)
            cid  = item.data(Qt.ItemDataRole.UserRole) if item else None
        from views.ar.statement_dialog import StatementDialog
        dlg = StatementDialog(customer_id=cid, parent=self)
        dlg.exec()
