"""
views/reports/gst_report.py
----------------------------
GST Report for BackOfficePro.
Shows GST collected on sales, GST paid on purchases, and BAS summary.
Supports Monthly, Quarterly (BAS), Financial Year, and Custom date ranges.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit,
    QFrame, QComboBox, QTabWidget, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from database.connection import get_connection
from datetime import date, timedelta
import csv
import os

RIGHT  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
LEFT   = Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fy_bounds(year=None):
    """Australian FY: 1 Jul → 30 Jun."""
    today = date.today()
    if year is None:
        year = today.year if today.month >= 7 else today.year - 1
    return date(year, 7, 1), date(year + 1, 6, 30)


def _bas_quarters():
    """Return the 4 BAS quarter labels and bounds for the current FY."""
    fy_s, _ = _fy_bounds()
    quarters = []
    for i in range(4):
        q_start = date(fy_s.year + (1 if i >= 2 else 0),
                       [7, 10, 1, 4][i], 1)
        q_end = date(
            q_start.year + (1 if q_start.month >= 10 else 0),
            [10, 1, 4, 7][i], 1
        ) - timedelta(days=1)
        label = f"Q{i+1} {q_start.strftime('%b')}–{q_end.strftime('%b %Y')}"
        quarters.append((label, q_start, q_end))
    return quarters


def _text_item(text, align=LEFT, color=None, bold=False):
    i = QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        i.setForeground(QColor(color))
    if bold:
        f = i.font(); f.setBold(True); i.setFont(f)
    return i


def _money_item(value: float, color=None, bold=False):
    i = QTableWidgetItem(f"${value:,.2f}")
    i.setTextAlignment(RIGHT)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        i.setForeground(QColor(color))
    if bold:
        f = i.font(); f.setBold(True); i.setFont(f)
    return i


# ── GST Calculations ──────────────────────────────────────────────────────────

def _calc_gst_collected(conn, d_from: date, d_to: date) -> dict:
    """
    Calculate GST collected on sales for a date range.
    Joins sales_daily → plu_barcode_map → products to find taxable PLUs.
    sales_dollars is GST-inclusive; GST = sales_dollars / 11.
    Returns dict with taxable_sales, exempt_sales, gst_collected, total_sales.
    """
    rows = conn.execute("""
        SELECT
            sd.sale_date,
            sd.plu,
            sd.plu_name,
            sd.sales_dollars,
            COALESCE(p.tax_rate, 0) AS tax_rate
        FROM sales_daily sd
        LEFT JOIN plu_barcode_map pbm ON CAST(sd.plu AS TEXT) = CAST(pbm.plu AS TEXT)
        LEFT JOIN products p ON pbm.barcode = p.barcode
        WHERE sd.sale_date BETWEEN ? AND ?
          AND sd.sales_dollars > 0
    """, (str(d_from), str(d_to))).fetchall()

    taxable_sales  = 0.0
    exempt_sales   = 0.0
    gst_collected  = 0.0

    for row in rows:
        dollars   = float(row['sales_dollars'])
        tax_rate  = float(row['tax_rate']) if row['tax_rate'] else 0.0
        if tax_rate > 0:
            taxable_sales += dollars
            gst_collected += dollars / (1 + tax_rate / 100) * (tax_rate / 100)
        else:
            exempt_sales  += dollars

    return {
        'taxable_sales':  round(taxable_sales,  2),
        'exempt_sales':   round(exempt_sales,   2),
        'total_sales':    round(taxable_sales + exempt_sales, 2),
        'gst_collected':  round(gst_collected,  2),
        'sales_ex_gst':   round(taxable_sales - gst_collected, 2),
    }


def _calc_gst_paid(conn, d_from: date, d_to: date) -> dict:
    """
    Calculate GST paid on purchases (received POs only) for a date range.
    Uses po_lines unit_cost × qty × pack_qty and product tax_rate.
    Returns dict with taxable_purchases, exempt_purchases, gst_paid, total_purchases.
    """
    rows = conn.execute("""
        SELECT
            pol.ordered_qty,
            pol.unit_cost,
            pol.barcode,
            COALESCE(p.tax_rate, 0)  AS tax_rate,
            COALESCE(p.pack_qty, 1)  AS pack_qty,
            po.received_at
        FROM po_lines pol
        JOIN purchase_orders po  ON po.id = pol.po_id
        LEFT JOIN products p     ON p.barcode = pol.barcode
        WHERE po.status = 'RECEIVED'
          AND DATE(po.received_at) BETWEEN ? AND ?
    """, (str(d_from), str(d_to))).fetchall()

    taxable_purchases = 0.0
    exempt_purchases  = 0.0
    gst_paid          = 0.0

    for row in rows:
        cartons   = int(row['ordered_qty'] or 0)
        pack_qty  = int(row['pack_qty']    or 1)
        unit_cost = float(row['unit_cost'] or 0)
        tax_rate  = float(row['tax_rate']  or 0)
        line_total = cartons * pack_qty * unit_cost

        if tax_rate > 0:
            taxable_purchases += line_total
            gst_paid += line_total / (1 + tax_rate / 100) * (tax_rate / 100)
        else:
            exempt_purchases  += line_total

    return {
        'taxable_purchases':  round(taxable_purchases, 2),
        'exempt_purchases':   round(exempt_purchases,  2),
        'total_purchases':    round(taxable_purchases + exempt_purchases, 2),
        'gst_paid':           round(gst_paid,          2),
        'purchases_ex_gst':   round(taxable_purchases - gst_paid, 2),
    }


# ── Main Widget ───────────────────────────────────────────────────────────────

class GSTReport(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._set_this_quarter()

    def showEvent(self, event):
        super().showEvent(event)
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel("GST Report")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(title)

        # ── Quick period buttons ───────────────────────────────────────
        period_row = QHBoxLayout()
        period_row.setSpacing(6)

        btn_style = (
            "QPushButton{background:#1e2a38;color:#e6edf3;border:1px solid #2a3a4a;"
            "border-radius:3px;padding:0 10px;font-size:11px;height:30px;}"
            "QPushButton:hover{background:#2a3a4a;}"
        )

        # BAS quarter buttons
        for label, q_start, q_end in _bas_quarters():
            btn = QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(lambda _, s=q_start, e=q_end: self._set_dates(s, e))
            period_row.addWidget(btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #2a3a4a;")
        period_row.addWidget(sep)

        for label, fn in [
            ("This Month",  self._set_this_month),
            ("Last Month",  self._set_last_month),
            ("This FY",     self._set_this_fy),
            ("Last FY",     self._set_last_fy),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(fn)
            period_row.addWidget(btn)

        period_row.addStretch()
        root.addLayout(period_row)

        # ── Date range + Apply ────────────────────────────────────────
        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        date_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setMinimumHeight(32)
        date_row.addWidget(self.date_from)
        date_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setMinimumHeight(32)
        date_row.addWidget(self.date_to)

        apply_btn = QPushButton("Apply")
        apply_btn.setMinimumHeight(32)
        apply_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:0 16px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        apply_btn.clicked.connect(self._load)
        date_row.addWidget(apply_btn)

        export_btn = QPushButton("⬇ Export CSV")
        export_btn.setMinimumHeight(32)
        export_btn.clicked.connect(self._export)
        date_row.addWidget(export_btn)

        date_row.addStretch()
        root.addLayout(date_row)

        # ── Tabs: BAS Summary / GST Collected / GST Paid ─────────────
        self.tabs = QTabWidget()

        # BAS Summary tab
        self.bas_widget = QWidget()
        bas_layout = QVBoxLayout(self.bas_widget)
        bas_layout.setContentsMargins(16, 16, 16, 16)
        bas_layout.setSpacing(12)
        self.bas_table = self._make_summary_table()
        self.bas_table.setMinimumHeight(400)
        bas_layout.addWidget(self.bas_table)
        bas_layout.addStretch()
        self.tabs.addTab(self.bas_widget, "📋 BAS Summary")

        # GST Collected tab
        self.collected_widget = QWidget()
        col_layout = QVBoxLayout(self.collected_widget)
        col_layout.setContentsMargins(8, 8, 8, 8)
        self.collected_table = self._make_detail_table([
            "Description", "Amount"
        ])
        col_layout.addWidget(self.collected_table)
        self.tabs.addTab(self.collected_widget, "💰 GST Collected")

        # GST Paid tab
        self.paid_widget = QWidget()
        paid_layout = QVBoxLayout(self.paid_widget)
        paid_layout.setContentsMargins(8, 8, 8, 8)
        self.paid_table = self._make_detail_table([
            "Description", "Amount"
        ])
        paid_layout.addWidget(self.paid_table)
        self.tabs.addTab(self.paid_widget, "🧾 GST Paid")

        root.addWidget(self.tabs)

        self.footer = QLabel("")
        self.footer.setStyleSheet("color: #8b949e; font-size: 11px;")
        root.addWidget(self.footer)

    def _make_summary_table(self):
        t = QTableWidget()
        t.setColumnCount(2)
        t.setHorizontalHeaderLabels(["Item", "Amount"])
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(1, 160)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        return t

    def _make_detail_table(self, headers):
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(1, 160)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        return t

    # ── Quick date setters ────────────────────────────────────────────
    def _set_dates(self, d_from: date, d_to: date):
        self.date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self.date_to.setDate(QDate(d_to.year,   d_to.month,   d_to.day))
        self._load()

    def _set_this_quarter(self):
        today = date.today()
        for _, q_start, q_end in _bas_quarters():
            if q_start <= today <= q_end:
                self._set_dates(q_start, min(q_end, today))
                return
        s, _ = _fy_bounds()
        self._set_dates(s, today)

    def _set_this_month(self):
        t = date.today()
        self._set_dates(t.replace(day=1), t)

    def _set_last_month(self):
        t = date.today()
        last_end = t.replace(day=1) - timedelta(days=1)
        self._set_dates(last_end.replace(day=1), last_end)

    def _set_this_fy(self):
        s, e = _fy_bounds()
        self._set_dates(s, min(e, date.today()))

    def _set_last_fy(self):
        t = date.today()
        y = t.year if t.month >= 7 else t.year - 1
        s, e = _fy_bounds(y - 1)
        self._set_dates(s, e)

    # ── Main load ─────────────────────────────────────────────────────
    def _load(self):
        d_from = self.date_from.date().toPyDate()
        d_to   = self.date_to.date().toPyDate()

        conn = get_connection()
        try:
            sales = _calc_gst_collected(conn, d_from, d_to)
            purch = _calc_gst_paid(conn, d_from, d_to)
        finally:
            conn.close()

        net_gst = round(sales['gst_collected'] - purch['gst_paid'], 2)
        period  = f"{d_from.strftime('%d/%m/%Y')} – {d_to.strftime('%d/%m/%Y')}"

        # ── BAS Summary table ─────────────────────────────────────────
        bas_rows = [
            # Label,                          value,             section
            ("SALES",                          None,              "header"),
            ("Total sales (inc GST)",          sales['total_sales'],       "normal"),
            ("GST-free sales",                 sales['exempt_sales'],      "normal"),
            ("Taxable sales (inc GST)  [G1]",  sales['taxable_sales'],     "normal"),
            ("Taxable sales (ex GST)",         sales['sales_ex_gst'],      "normal"),
            ("GST collected on sales  [1A]",   sales['gst_collected'],     "highlight"),
            ("",                               None,              "spacer"),
            ("PURCHASES",                      None,              "header"),
            ("Total purchases (inc GST)",      purch['total_purchases'],   "normal"),
            ("GST-free purchases",             purch['exempt_purchases'],  "normal"),
            ("Taxable purchases (inc GST)",    purch['taxable_purchases'], "normal"),
            ("Taxable purchases (ex GST)",     purch['purchases_ex_gst'],  "normal"),
            ("GST paid on purchases  [1B]",    purch['gst_paid'],          "paid"),
            ("",                               None,              "spacer"),
            ("NET GST PAYABLE  [1A – 1B]",     net_gst,           "net"),
        ]

        self.bas_table.setRowCount(len(bas_rows))
        for r, (label, value, kind) in enumerate(bas_rows):
            if kind == "spacer":
                self.bas_table.setItem(r, 0, _text_item(""))
                self.bas_table.setItem(r, 1, _text_item(""))
                self.bas_table.setRowHeight(r, 10)
                continue
            if kind == "header":
                self.bas_table.setItem(r, 0, _text_item(label, bold=True, color="#8b949e"))
                self.bas_table.setItem(r, 1, _text_item(""))
                continue

            bold      = kind in ("highlight", "paid", "net")
            color_val = (
                "#4CAF50" if kind == "highlight" else
                "#EF9F27" if kind == "paid" else
                "#E24B4A" if kind == "net" and net_gst > 0 else
                "#4CAF50" if kind == "net" else
                None
            )
            self.bas_table.setItem(r, 0, _text_item(label, bold=bold))
            self.bas_table.setItem(r, 1, _money_item(value, color=color_val, bold=bold))

        # ── GST Collected detail ──────────────────────────────────────
        col_rows = [
            ("Total sales (inc GST)",         sales['total_sales'],      False),
            ("  GST-free sales",              sales['exempt_sales'],     False),
            ("  Taxable sales (inc GST)",     sales['taxable_sales'],    False),
            ("  Taxable sales (ex GST)",      sales['sales_ex_gst'],     False),
            ("GST collected  [1A]",           sales['gst_collected'],    True),
        ]
        self.collected_table.setRowCount(len(col_rows))
        for r, (label, value, bold) in enumerate(col_rows):
            color = "#4CAF50" if bold else None
            self.collected_table.setItem(r, 0, _text_item(label, bold=bold))
            self.collected_table.setItem(r, 1, _money_item(value, color=color, bold=bold))

        # ── GST Paid detail ───────────────────────────────────────────
        paid_rows = [
            ("Total purchases (inc GST)",         purch['total_purchases'],   False),
            ("  GST-free purchases",              purch['exempt_purchases'],  False),
            ("  Taxable purchases (inc GST)",     purch['taxable_purchases'], False),
            ("  Taxable purchases (ex GST)",      purch['purchases_ex_gst'],  False),
            ("GST paid on purchases  [1B]",       purch['gst_paid'],          True),
        ]
        self.paid_table.setRowCount(len(paid_rows))
        for r, (label, value, bold) in enumerate(paid_rows):
            color = "#EF9F27" if bold else None
            self.paid_table.setItem(r, 0, _text_item(label, bold=bold))
            self.paid_table.setItem(r, 1, _money_item(value, color=color, bold=bold))

        self.footer.setText(
            f"Period: {period}  |  "
            f"GST collected: ${sales['gst_collected']:,.2f}  |  "
            f"GST paid: ${purch['gst_paid']:,.2f}  |  "
            f"Net payable: ${net_gst:,.2f}"
        )

        # Store for export
        self._last_sales = sales
        self._last_purch = purch
        self._last_net   = net_gst
        self._last_period = period

    # ── Export ────────────────────────────────────────────────────────
    def _export(self):
        if not hasattr(self, '_last_sales'):
            QMessageBox.warning(self, "No Data", "Load a report first.")
            return

        default = os.path.join(
            os.path.expanduser("~"), "Documents",
            f"GST_Report_{date.today().strftime('%Y%m%d')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export GST Report", default, "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["GST Report"])
                w.writerow(["Period", self._last_period])
                w.writerow([])
                w.writerow(["SALES"])
                w.writerow(["Total sales (inc GST)",        f"${self._last_sales['total_sales']:,.2f}"])
                w.writerow(["GST-free sales",               f"${self._last_sales['exempt_sales']:,.2f}"])
                w.writerow(["Taxable sales (inc GST) [G1]", f"${self._last_sales['taxable_sales']:,.2f}"])
                w.writerow(["Taxable sales (ex GST)",       f"${self._last_sales['sales_ex_gst']:,.2f}"])
                w.writerow(["GST collected [1A]",           f"${self._last_sales['gst_collected']:,.2f}"])
                w.writerow([])
                w.writerow(["PURCHASES"])
                w.writerow(["Total purchases (inc GST)",         f"${self._last_purch['total_purchases']:,.2f}"])
                w.writerow(["GST-free purchases",                f"${self._last_purch['exempt_purchases']:,.2f}"])
                w.writerow(["Taxable purchases (inc GST)",       f"${self._last_purch['taxable_purchases']:,.2f}"])
                w.writerow(["Taxable purchases (ex GST)",        f"${self._last_purch['purchases_ex_gst']:,.2f}"])
                w.writerow(["GST paid on purchases [1B]",        f"${self._last_purch['gst_paid']:,.2f}"])
                w.writerow([])
                w.writerow(["NET GST PAYABLE [1A - 1B]",         f"${self._last_net:,.2f}"])

            QMessageBox.information(self, "Exported", f"GST report saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))
