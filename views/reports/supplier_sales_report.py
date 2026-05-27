from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QDateEdit, QFrame
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
import config.styles as styles
import controllers.report_controller as report_ctrl
from views.base_view import BaseView
from datetime import date, timedelta
from utils.calculations import week_bounds, fy_bounds

RIGHT  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
LEFT   = Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter

BARCODE_ROLE = Qt.ItemDataRole.UserRole


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
    i.setForeground(QColor(color or (styles.CLR_SUCCESS_ALT if value > 0 else styles.CLR_EXTRA_DIM)))
    if bold:
        f = i.font(); f.setBold(True); i.setFont(f)
    return i


class SupplierSalesReport(BaseView):
    def __init__(self):
        super().__init__()
        self._edit_wins = []
        self._build_ui()
        self._load_suppliers()
        self.load()

    def showEvent(self, event):
        super().showEvent(event)
        self.load()

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
        sep.setStyleSheet(styles.STYLE_SEPARATOR)
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
            btn.setStyleSheet(styles.STYLE_BTN_PERIOD)
            btn.clicked.connect(fn)
            filter_row.addWidget(btn)

        filter_row.addStretch()
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(32)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:0 16px;font-weight:bold;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}")
        apply_btn.clicked.connect(self.load)
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
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "Supplier", "Barcode", "Description",
            "This Week", "Last Week", "2 Wks Ago",
            "This Month", "Last Month",
            "This FY", "Last FY", "All Time",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c in [0, 1, 3, 4, 5, 6, 7, 8, 9, 10]:
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(3,  75)
        self.table.setColumnWidth(4,  75)
        self.table.setColumnWidth(5,  75)
        self.table.setColumnWidth(6,  90)
        self.table.setColumnWidth(7,  90)
        self.table.setColumnWidth(8,  80)
        self.table.setColumnWidth(9,  80)
        self.table.setColumnWidth(10, 80)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.doubleClicked.connect(self._open_product)
        root.addWidget(self.table)

        self.totals_bar = QTableWidget()
        self.totals_bar.setColumnCount(11)
        self.totals_bar.setRowCount(1)
        self.totals_bar.horizontalHeader().setVisible(False)
        self.totals_bar.verticalHeader().setVisible(False)
        self.totals_bar.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.totals_bar.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.totals_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.totals_bar.setFixedHeight(30)
        self.totals_bar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.totals_bar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.totals_bar.setStyleSheet(f"QTableWidget {{ background: {styles.CLR_BG}; border: none; }}")
        tb_hdr = self.totals_bar.horizontalHeader()
        tb_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c in [0, 1, 3, 4, 5, 6, 7, 8, 9, 10]:
            tb_hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().sectionResized.connect(
            lambda col, _, new_size: self.totals_bar.setColumnWidth(col, new_size)
        )
        root.addWidget(self.totals_bar)

        self.footer = QLabel("")
        self.footer.setStyleSheet(styles.STYLE_LABEL_MUTED)
        root.addWidget(self.footer)

    def _load_suppliers(self):
        self.supplier_combo.clear()
        self.supplier_combo.addItem("All Suppliers", None)
        for r in report_ctrl.get_all_suppliers():
            self.supplier_combo.addItem(r['name'], r['id'])

    def _set_dates(self, d_from, d_to):
        self.date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self.date_to.setDate(QDate(d_to.year, d_to.month, d_to.day))

    def _set_this_week(self):
        t = date.today(); self._set_dates(t - timedelta(days=t.weekday()), t); self.load()
    def _set_last_week(self):
        s, e = week_bounds(0); self._set_dates(s, e); self.load()
    def _set_this_month(self):
        t = date.today(); self._set_dates(t.replace(day=1), t); self.load()
    def _set_last_month(self):
        t = date.today(); fe = t.replace(day=1) - timedelta(days=1)
        self._set_dates(fe.replace(day=1), fe); self.load()
    def _set_this_fy(self):
        s, e = fy_bounds(); self._set_dates(s, min(e, date.today())); self.load()
    def _set_last_fy(self):
        t = date.today()
        y = t.year if t.month >= 7 else t.year - 1
        s, e = fy_bounds(y - 1); self._set_dates(s, e); self.load()
    def _set_all_time(self):
        self._set_dates(date(2000, 1, 1), date.today()); self.load()

    def _load(self):
        supplier_id       = self.supplier_combo.currentData()
        computed, totals  = report_ctrl.get_supplier_sales(supplier_id)

        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(computed))

        for r, row in enumerate(computed):
            sup_item = _text_item(row['supplier_name'])
            sup_item.setData(BARCODE_ROLE, row['barcode'])
            self.table.setItem(r, 0, sup_item)
            self.table.setItem(r, 1, _text_item(row['barcode']))
            self.table.setItem(r, 2, _text_item(row['description']))
            for ci, val in enumerate(row['qty'], start=3):
                self.table.setItem(r, ci, _num_item(val))

        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)

        self.totals_bar.setItem(0, 0, _text_item("TOTALS", bold=True, color=styles.CLR_TEXT))
        self.totals_bar.setItem(0, 1, _text_item(""))
        self.totals_bar.setItem(0, 2, _text_item(""))
        for c in range(11):
            self.totals_bar.setColumnWidth(c, self.table.columnWidth(c))
        for ci, val in enumerate(totals, start=3):
            self.totals_bar.setItem(0, ci, _num_item(val, color=styles.CLR_AMBER, bold=True))

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
        def _is_alive(w):
            try:
                w.isHidden()
                return True
            except RuntimeError:
                return False
        self._edit_wins = [w for w in self._edit_wins if _is_alive(w)]
        self._edit_wins.append(win)
