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

BARCODE_ROLE = Qt.ItemDataRole.UserRole


def _week_bounds(offset=0):
    today = date.today()
    mon   = today - timedelta(days=today.weekday())
    start = mon - timedelta(weeks=(1 - offset))
    return start, start + timedelta(days=6)

def _fy_bounds(year=None):
    today = date.today()
    if year is None:
        year = today.year if today.month >= 7 else today.year - 1
    return date(year, 7, 1), date(year + 1, 6, 30)


class _NumItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return int(self.data(Qt.ItemDataRole.UserRole) or 0) < \
                   int(other.data(Qt.ItemDataRole.UserRole) or 0)
        except (TypeError, ValueError):
            return self.text() < other.text()


def _text_item(text, align=LEFT, bold=False, color=None):
    i = QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        i.setForeground(QColor(color))
    if bold:
        f = i.font(); f.setBold(True); i.setFont(f)
    return i


def _num_item(value: int, align=RIGHT, bold=False, color=None):
    i = _NumItem("—" if value == 0 else f"{value:,}")
    i.setData(Qt.ItemDataRole.UserRole, value)
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    i.setForeground(QColor(color or ("#4CAF50" if value > 0 else "#6e7681")))
    if bold:
        f = i.font(); f.setBold(True); i.setFont(f)
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

        title = QLabel("Sales by Supplier")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(title)

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

        for label, fn in [
            ("This Week",  self._set_this_week),
            ("Last Week",  self._set_last_week),
            ("This Month", self._set_this_month),
            ("Last Month", self._set_last_month),
            ("This FY",    self._set_this_fy),
            ("Last FY",    self._set_last_fy),
            ("All Time",   self._set_all_time),
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

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Supplier", "Barcode", "Description",
            "Last Week", "2 Wks Ago",
            "This Month", "Last Month",
            "This FY", "Last FY", "All Time",
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
        self.table.setSortingEnabled(False)
        self.table.doubleClicked.connect(self._open_product)
        root.addWidget(self.table)

        self.totals_bar = QTableWidget()
        self.totals_bar.setColumnCount(10)
        self.totals_bar.setRowCount(1)
        self.totals_bar.horizontalHeader().setVisible(False)
        self.totals_bar.verticalHeader().setVisible(False)
        self.totals_bar.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.totals_bar.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.totals_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.totals_bar.setFixedHeight(30)
        self.totals_bar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.totals_bar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.totals_bar.setStyleSheet("QTableWidget { background: #1a2332; border: none; }")
        tb_hdr = self.totals_bar.horizontalHeader()
        tb_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c in [0, 1, 3, 4, 5, 6, 7, 8, 9]:
            tb_hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().sectionResized.connect(
            lambda col, _, new_size: self.totals_bar.setColumnWidth(col, new_size)
        )
        root.addWidget(self.totals_bar)

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

    def _set_dates(self, d_from, d_to):
        self.date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self.date_to.setDate(QDate(d_to.year, d_to.month, d_to.day))

    def _set_this_week(self):
        t = date.today(); self._set_dates(t - timedelta(days=t.weekday()), t); self._load()
    def _set_last_week(self):
        s, e = _week_bounds(0); self._set_dates(s, e); self._load()
    def _set_this_month(self):
        t = date.today(); self._set_dates(t.replace(day=1), t); self._load()
    def _set_last_month(self):
        t = date.today(); fe = t.replace(day=1) - timedelta(days=1)
        self._set_dates(fe.replace(day=1), fe); self._load()
    def _set_this_fy(self):
        s, e = _fy_bounds(); self._set_dates(s, min(e, date.today())); self._load()
    def _set_last_fy(self):
        t = date.today()
        y = t.year if t.month >= 7 else t.year - 1
        s, e = _fy_bounds(y - 1); self._set_dates(s, e); self._load()
    def _set_all_time(self):
        self._set_dates(date(2000, 1, 1), date.today()); self._load()

    def _load(self):
        conn = get_connection()
        supplier_id = self.supplier_combo.currentData()
        today       = date.today()

        lw_s, lw_e   = _week_bounds(0)
        tw_s, tw_e   = _week_bounds(1)
        tm_s         = today.replace(day=1)
        lm_e         = tm_s - timedelta(days=1)
        lm_s         = lm_e.replace(day=1)
        fy_s, fy_e   = _fy_bounds()
        pfy_s, pfy_e = _fy_bounds((today.year if today.month >= 7 else today.year - 1) - 1)

        def qty(plu, d1, d2):
            r = conn.execute("""
                SELECT COALESCE(SUM(quantity), 0) FROM sales_daily
                WHERE plu=? AND sale_date BETWEEN ? AND ?
            """, (plu, str(d1), str(d2))).fetchone()
            return int(r[0]) if r else 0

        sup_filter = "AND p.supplier_id = ?" if supplier_id else ""
        sup_params = [supplier_id] if supplier_id else []

        db_rows = conn.execute(f"""
            SELECT
                p.barcode,
                p.description,
                s.name AS supplier_name,
                COALESCE(pbm.plu, '') AS plu
            FROM products p
            JOIN suppliers s ON s.id = p.supplier_id
            LEFT JOIN plu_barcode_map pbm ON pbm.barcode = p.barcode
            WHERE p.active = 1
              {sup_filter}
            ORDER BY s.name, p.description
        """, sup_params).fetchall()
        computed = []
        totals   = [0] * 7

        for row in db_rows:
            barcode     = row[0]
            description = row[1]
            sup_name    = row[2]
            plu         = str(row[3]) if row[3] else None

            vals = [
                qty(plu, lw_s,  lw_e),
                qty(plu, tw_s,  tw_e),
                qty(plu, tm_s,  today),
                qty(plu, lm_s,  lm_e),
                qty(plu, fy_s,  fy_e),
                qty(plu, pfy_s, pfy_e),
                qty(plu, date(2000, 1, 1), today),
            ] if plu else [0] * 7

            for i, v in enumerate(vals):
                totals[i] += v

            computed.append((barcode, description, sup_name, vals))

        conn.close()

        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(computed))

        for r, (barcode, description, sup_name, vals) in enumerate(computed):
            sup_item = _text_item(sup_name)
            sup_item.setData(BARCODE_ROLE, barcode)
            self.table.setItem(r, 0, sup_item)
            self.table.setItem(r, 1, _text_item(barcode))
            self.table.setItem(r, 2, _text_item(description))
            for ci, val in enumerate(vals, start=3):
                self.table.setItem(r, ci, _num_item(val))

        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)

        self.totals_bar.setItem(0, 0, _text_item("TOTALS", bold=True, color="#e6edf3"))
        self.totals_bar.setItem(0, 1, _text_item(""))
        self.totals_bar.setItem(0, 2, _text_item(""))
        for c in range(10):
            self.totals_bar.setColumnWidth(c, self.table.columnWidth(c))
        for ci, val in enumerate(totals, start=3):
            self.totals_bar.setItem(0, ci, _num_item(val, color="#FFB300", bold=True))

        self.footer.setText(
            f"{len(computed)} products  |  Double-click a row to open product detail"
        )

    def _open_product(self, index):
        sibling = index.siblingAtColumn(0)
        barcode = sibling.data(BARCODE_ROLE)
        if not barcode:
            return
        from views.products.product_edit import ProductEdit
        win = ProductEdit(barcode=barcode)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.show()
        win.raise_()
        win.activateWindow()
        self._edit_wins = [w for w in self._edit_wins if not w.isHidden()]
        self._edit_wins.append(win)
