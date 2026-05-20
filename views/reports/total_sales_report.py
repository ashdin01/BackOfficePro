"""Combined POS + AR invoiced revenue report."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit, QFrame,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QFont

from database.connection import get_connection


# ── helpers ───────────────────────────────────────────────────────────────────

def _fetch(d_from: str, d_to: str) -> dict:
    """Return {date_str: {'pos': float, 'ar': float}} for the date range."""
    conn = get_connection()
    try:
        pos_rows = conn.execute("""
            SELECT sale_date, SUM(sales_dollars) AS total
            FROM sales_daily
            WHERE sale_date BETWEEN ? AND ?
            GROUP BY sale_date
        """, (d_from, d_to)).fetchall()

        ar_rows = conn.execute("""
            SELECT invoice_date, SUM(total) AS total
            FROM ar_invoices
            WHERE invoice_date BETWEEN ? AND ?
              AND status NOT IN ('VOID', 'DRAFT')
            GROUP BY invoice_date
        """, (d_from, d_to)).fetchall()
    finally:
        conn.close()

    data: dict = {}
    for r in pos_rows:
        data.setdefault(r['sale_date'], {'pos': 0.0, 'ar': 0.0})['pos'] = float(r['total'] or 0)
    for r in ar_rows:
        data.setdefault(r['invoice_date'], {'pos': 0.0, 'ar': 0.0})['ar'] = float(r['total'] or 0)
    return data


def _stat_card(label: str, value: str, colour: str = '#1565c0') -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.StyledPanel)
    f.setStyleSheet(f"""
        QFrame {{
            background: #1e2a38;
            border: 1px solid {colour};
            border-radius: 6px;
            padding: 8px;
        }}
    """)
    v = QVBoxLayout(f)
    v.setSpacing(2)
    lbl = QLabel(label)
    lbl.setStyleSheet("color: #8b949e; font-size: 11px; border: none;")
    val = QLabel(value)
    bold = QFont(); bold.setBold(True); bold.setPointSize(16)
    val.setFont(bold)
    val.setStyleSheet(f"color: {colour}; border: none;")
    v.addWidget(lbl)
    v.addWidget(val)
    return f


# ── widget ────────────────────────────────────────────────────────────────────

class TotalSalesReport(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Total Sales")
        self.resize(820, 560)
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── date range ───────────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setDate(QDate.currentDate().addDays(-QDate.currentDate().day() + 1))
        bar.addWidget(self.date_from)

        bar.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDate(QDate.currentDate())
        bar.addWidget(self.date_to)

        btn_run = QPushButton("Run")
        btn_run.clicked.connect(self._load)
        bar.addWidget(btn_run)
        bar.addStretch()
        root.addLayout(bar)

        # ── stat cards ───────────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        self.card_pos      = _stat_card("POS Sales",    "$0.00", '#1565c0')
        self.card_ar       = _stat_card("AR Invoiced",  "$0.00", '#e65100')
        self.card_combined = _stat_card("Combined",     "$0.00", '#2e7d32')
        cards_row.addWidget(self.card_pos)
        cards_row.addWidget(self.card_ar)
        cards_row.addWidget(self.card_combined)
        root.addLayout(cards_row)

        # ── daily table ──────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Date", "POS Sales", "AR Invoiced", "Day Total"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        root.addWidget(self.table)

    def _load(self):
        d_from = self.date_from.date().toString("yyyy-MM-dd")
        d_to   = self.date_to.date().toString("yyyy-MM-dd")
        data   = _fetch(d_from, d_to)

        total_pos = sum(v['pos'] for v in data.values())
        total_ar  = sum(v['ar']  for v in data.values())
        combined  = total_pos + total_ar

        # update stat cards
        self.card_pos.findChild(QLabel, "", Qt.FindChildOption.FindDirectChildrenOnly)
        _update_card(self.card_pos,      f"${total_pos:.2f}")
        _update_card(self.card_ar,       f"${total_ar:.2f}")
        _update_card(self.card_combined, f"${combined:.2f}")

        rows = sorted(data.items())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, (dt, vals) in enumerate(rows):
            pos  = vals['pos']
            ar   = vals['ar']
            day  = pos + ar
            for j, (txt, align) in enumerate([
                (dt,              Qt.AlignmentFlag.AlignLeft),
                (f"${pos:.2f}",   Qt.AlignmentFlag.AlignRight),
                (f"${ar:.2f}",    Qt.AlignmentFlag.AlignRight),
                (f"${day:.2f}",   Qt.AlignmentFlag.AlignRight),
            ]):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                if j == 1 and pos == 0:
                    item.setForeground(QColor('#555'))
                if j == 2 and ar == 0:
                    item.setForeground(QColor('#555'))
                self.table.setItem(i, j, item)
        self.table.setSortingEnabled(True)


def _update_card(frame: QFrame, value: str):
    labels = frame.findChildren(QLabel)
    if len(labels) >= 2:
        labels[1].setText(value)
