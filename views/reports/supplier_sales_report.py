from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QDateEdit, QFrame
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from database.connection import get_connection
from datetime import date, timedelta


RIGHT  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
LEFT   = Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter


def _week_bounds(offset=0):
    """Return (start, end) for a Mon-Sun week. offset=0=last week, -1=two weeks ago."""
    today = date.today()
    mon = today - timedelta(days=today.weekday())   # this Monday
    start = mon - timedelta(weeks=(1 - offset))
    end   = start + timedelta(days=6)
    return start, end


def _fy_bounds(year=None):
    """Australian FY: 1 Jul → 30 Jun. year=None = current FY."""
    today = date.today()
    if year is None:
        fy_start_year = today.year if today.month >= 7 else today.year - 1
    else:
        fy_start_year = year
    return date(fy_start_year, 7, 1), date(fy_start_year + 1, 6, 30)


class _NumItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text().replace(",", "")) < \
                   float(other.text().replace(",", ""))
        except ValueError:
            return self.text() < other.text()


def _item(text, align=LEFT, numeric=False, color=None):
    i = _NumItem(str(text)) if numeric else QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        i.setForeground(QColor(color))
    return i


class SupplierSalesReport(QWidget):
    def __init__(self):
        super().__init__()
        self._edit_wins = []
        self._build_ui()
        self._load_suppliers()
        self._load()

    def showEvent(self, event):
        super().showEvent(event)
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel("Sales by Supplier")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(title)

        # ── Filter row ────────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("Supplier:"))
        self.supplier_combo = QComboBox()
        self.supplier_combo.setMinimumWidth(200)
        self.supplier_combo.setMinimumHeight(32)
        filter_row.addWidget(self.supplier_combo)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #2a3a4a;")
        filter_row.addWidget(sep)

        # Quick date buttons
        for label, fn in [
            ("This Week",     self._set_this_week),
            ("Last Week",     self._set_last_week),
            ("This Month",    self._set_this_month),
            ("Last Month",    self._set_last_month),
            ("This FY",       self._set_this_fy),
            ("Last FY",       self._set_last_fy),
            ("All Time",      self._set_all_time),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                "QPushButton{background:#1e2a38;color:#e6edf3;border:1px solid #2a3a4a;"
                "border-radius:3px;padding:0 8px;font-size:11px;}"
                "QPushButton:hover{background:#2a3a4a;}")
            btn.clicked.connect(fn)
            filter_row.addWidget(btn)

        filter_row.addStretch()

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(32)
        apply_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:0 16px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}")
        apply_btn.clicked.connect(self._load)
        filter_row.addWidget(apply_btn)

        root.addLayout(filter_row)

        # ── Date range row ────────────────────────────────────────────
        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        date_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_from.setMinimumHeight(32)
        date_row.addWidget(self.date_from)

        date_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setMinimumHeight(32)
        date_row.addWidget(self.date_to)
        date_row.addStretch()
        root.addLayout(date_row)

        # ── Table ─────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Supplier", "Barcode", "Description",
            "Last Week", "2 Wks Ago",
            "This Month", "Last Month",
            "This FY", "Last FY",
            "All Time",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c in [0, 1, 3, 4, 5, 6, 7, 8, 9]:
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(3,  75)
        self.table.setColumnWidth(4,  75)
        self.table.setColumnWidth(5,  90)
        self.table.setColumnWidth(6,  90)
        self.table.setColumnWidth(7,  80)
        self.table.setColumnWidth(8,  80)
        self.table.setColumnWidth(9,  80)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._open_product)
        root.addWidget(self.table)

        # ── Footer ────────────────────────────────────────────────────
        self.footer = QLabel("")
        self.footer.setStyleSheet("color: #8b949e; font-size: 11px;")
        root.addWidget(self.footer)

    def _load_suppliers(self):
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, name FROM suppliers WHERE active=1 ORDER BY name"
        ).fetchall()
        conn.close()
        self.supplier_combo.clear()
        self.supplier_combo.addItem("All Suppliers", None)
        for r in rows:
            self.supplier_combo.addItem(r[1], r[0])

    # ── Quick date setters ────────────────────────────────────────────
    def _set_dates(self, d_from: date, d_to: date):
        self.date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self.date_to.setDate(QDate(d_to.year, d_to.month, d_to.day))

    def _set_this_week(self):
        today = date.today()
        self._set_dates(today - timedelta(days=today.weekday()), today)
        self._load()

    def _set_last_week(self):
        s, e = _week_bounds(0)
        self._set_dates(s, e); self._load()

    def _set_this_month(self):
        today = date.today()
        self._set_dates(today.replace(day=1), today); self._load()

    def _set_last_month(self):
        today = date.today()
        first = today.replace(day=1)
        last_end = first - timedelta(days=1)
        last_start = last_end.replace(day=1)
        self._set_dates(last_start, last_end); self._load()

    def _set_this_fy(self):
        s, e = _fy_bounds()
        self._set_dates(s, min(e, date.today())); self._load()

    def _set_last_fy(self):
        today = date.today()
        fy_year = today.year if today.month >= 7 else today.year - 1
        s, e = _fy_bounds(fy_year - 1)
        self._set_dates(s, e); self._load()

    def _set_all_time(self):
        self._set_dates(date(2000, 1, 1), date.today()); self._load()

    # ── Main load ─────────────────────────────────────────────────────
    def _load(self):
        conn = get_connection()

        supplier_id = self.supplier_combo.currentData()
        d_from = self.date_from.date().toString("yyyy-MM-dd")
        d_to   = self.date_to.date().toString("yyyy-MM-dd")

        today = date.today()

        # Period bounds
        lw_s, lw_e   = _week_bounds(0)
        tw_s, tw_e   = _week_bounds(1)
        tm_s         = today.replace(day=1)
        lm_e         = tm_s - timedelta(days=1)
        lm_s         = lm_e.replace(day=1)
        fy_s, fy_e   = _fy_bounds()
        pfy_s, pfy_e = _fy_bounds(
            (today.year if today.month >= 7 else today.year - 1) - 1)

        def qty(plu, d1, d2):
            r = conn.execute("""
                SELECT COALESCE(SUM(quantity),0) FROM sales_daily
                WHERE plu=? AND sale_date BETWEEN ? AND ?
            """, (plu, str(d1), str(d2))).fetchone()
            return int(r[0]) if r else 0

        # Build supplier filter
        sup_filter = ""
        sup_params = []
        if supplier_id:
            sup_filter = "AND p.supplier_id = ?"
            sup_params = [supplier_id]

        # Get all matched products with sales in date range
        rows = conn.execute(f"""
            SELECT DISTINCT
                sd.plu,
                p.barcode,
                p.description,
                s.name  AS supplier_name,
                s.id    AS supplier_id
            FROM sales_daily sd
            JOIN plu_barcode_map pbm ON pbm.plu = CAST(sd.plu AS INTEGER)
            JOIN products p  ON p.barcode = pbm.barcode
            JOIN suppliers s ON s.id = p.supplier_id
            WHERE sd.sale_date BETWEEN ? AND ?
              AND p.active = 1
              {sup_filter}
            ORDER BY s.name, p.description
        """, [d_from, d_to] + sup_params).fetchall()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._row_barcodes = []

        totals = [0] * 7   # lw, tw, tm, lm, fy, pfy, alltime

        for row in rows:
            plu         = str(row[0])
            barcode     = row[1]
            description = row[2]
            sup_name    = row[3]

            lw   = qty(plu, lw_s,  lw_e)
            tw   = qty(plu, tw_s,  tw_e)
            tm   = qty(plu, tm_s,  today)
            lm   = qty(plu, lm_s,  lm_e)
            fy   = qty(plu, fy_s,  fy_e)
            pfy  = qty(plu, pfy_s, pfy_e)
            all_ = qty(plu, date(2000,1,1), today)

            totals[0] += lw;  totals[1] += tw
            totals[2] += tm;  totals[3] += lm
            totals[4] += fy;  totals[5] += pfy
            totals[6] += all_

            r = self.table.rowCount()
            self.table.insertRow(r)
            self._row_barcodes.append(barcode)

            self.table.setItem(r, 0, _item(sup_name))
            self.table.setItem(r, 1, _item(barcode))
            self.table.setItem(r, 2, _item(description))

            for ci, val in enumerate([lw, tw, tm, lm, fy, pfy, all_], start=3):
                color = "#4CAF50" if val > 0 else "#6e7681"
                self.table.setItem(r, ci,
                    _item(f"{val:,}" if val > 0 else "—", RIGHT,
                          numeric=True, color=color))

        conn.close()

        # Totals row
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._row_barcodes.append(None)
        total_item = _item("TOTALS", LEFT)
        total_item.setForeground(QColor("#e6edf3"))
        f = total_item.font(); f.setBold(True); total_item.setFont(f)
        self.table.setItem(r, 0, total_item)
        self.table.setItem(r, 1, _item(""))
        self.table.setItem(r, 2, _item(""))
        for ci, val in enumerate(totals, start=3):
            ti = _item(f"{val:,}", RIGHT, numeric=True, color="#FFB300")
            f = ti.font(); f.setBold(True); ti.setFont(f)
            self.table.setItem(r, ci, ti)

        self.table.setSortingEnabled(True)
        self.footer.setText(
            f"{len(rows)} products  |  {d_from} to {d_to}  |  "
            f"Double-click a row to open product detail"
        )

    def _open_product(self, index):
        row = index.row()
        if row >= len(self._row_barcodes):
            return
        barcode = self._row_barcodes[row]
        if not barcode:
            return
        from views.products.product_edit import ProductEdit
        win = ProductEdit(barcode=barcode)
        win.show()
        self._edit_wins.append(win)
