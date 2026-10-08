"""Top Sellers report — best-selling PLUs by date range and department."""
import csv
import os
from datetime import date, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QDateEdit, QFrame, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QDate
import config.styles as styles
import controllers.report_controller as report_ctrl
from views.base_view import BaseView
from utils.calculations import fy_bounds
from utils.error_dialog import show_error

RIGHT  = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
LEFT   = Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter

SORT_ROLE = Qt.ItemDataRole.UserRole

_HEADERS = ["#", "PLU", "Item", "Department", "Units", "Weight (kg)",
            "By Weight", "Sales $"]
_LIMITS = [25, 50, 100]


class _SortItem(QTableWidgetItem):
    """Sorts on the raw number stored in UserRole, not the display text."""
    def __lt__(self, other):
        try:
            return float(self.data(SORT_ROLE)) < float(other.data(SORT_ROLE))
        except (TypeError, ValueError):
            return self.text() < other.text()


def _text_item(text, align=LEFT):
    i = QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return i


def _num_item(display, value, align=RIGHT):
    i = _SortItem(display)
    i.setData(SORT_ROLE, value)
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return i


class TopSellersReport(BaseView):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Top Sellers")
        self._rows = []
        self._build_ui()
        self._load_departments()
        self._set_last_4_weeks(load=False)
        self.load()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Top Sellers")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(title)

        # Row 1 — period presets
        presets = QHBoxLayout()
        presets.setSpacing(8)
        for label, fn in [
            ("This Week",     self._set_this_week),
            ("Last 4 Weeks",  self._set_last_4_weeks),
            ("This Month",    self._set_this_month),
            ("This FY",       self._set_this_fy),
            ("All Time",      self._set_all_time),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setStyleSheet(styles.STYLE_BTN_PERIOD)
            btn.clicked.connect(lambda _=False, f=fn: f())
            presets.addWidget(btn)
        presets.addStretch()
        root.addLayout(presets)

        # Row 2 — filters
        filters = QHBoxLayout()
        filters.setSpacing(8)

        filters.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setMinimumHeight(32)
        filters.addWidget(self.date_from)

        filters.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setMinimumHeight(32)
        filters.addWidget(self.date_to)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(styles.STYLE_SEPARATOR)
        filters.addWidget(sep)

        filters.addWidget(QLabel("Department:"))
        self.dept_combo = QComboBox()
        self.dept_combo.setMinimumWidth(170)
        self.dept_combo.setMinimumHeight(32)
        filters.addWidget(self.dept_combo)

        filters.addWidget(QLabel("Rank by:"))
        self.rank_combo = QComboBox()
        self.rank_combo.addItem("Units", "units")
        self.rank_combo.addItem("Sales $", "sales")
        self.rank_combo.setMinimumHeight(32)
        filters.addWidget(self.rank_combo)

        filters.addWidget(QLabel("Show:"))
        self.limit_combo = QComboBox()
        for n in _LIMITS:
            self.limit_combo.addItem(f"Top {n}", n)
        self.limit_combo.setCurrentIndex(_LIMITS.index(50))
        self.limit_combo.setMinimumHeight(32)
        filters.addWidget(self.limit_combo)

        self.weighed_only = QCheckBox("Weighed items only")
        filters.addWidget(self.weighed_only)

        filters.addStretch()

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(32)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:0 16px;font-weight:bold;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}")
        apply_btn.clicked.connect(self.load)
        filters.addWidget(apply_btn)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setFixedHeight(32)
        self.export_btn.clicked.connect(self._export)
        filters.addWidget(self.export_btn)
        root.addLayout(filters)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c in (0, 1, 3, 4, 5, 6, 7):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        for c, w in zip((0, 1, 3, 4, 5, 6, 7), (45, 70, 150, 80, 100, 80, 100)):
            self.table.setColumnWidth(c, w)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)

        self.footer = QLabel("")
        self.footer.setStyleSheet(styles.STYLE_LABEL_MUTED)
        root.addWidget(self.footer)

    # ── Filters ───────────────────────────────────────────────────────
    def _load_departments(self):
        self.dept_combo.clear()
        self.dept_combo.addItem("All Departments", None)
        for d in report_ctrl.get_all_departments():
            self.dept_combo.addItem(d['name'], d['id'])

    def _set_dates(self, d_from, d_to, load=True):
        self.date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self.date_to.setDate(QDate(d_to.year, d_to.month, d_to.day))
        if load:
            self.load()

    def _set_this_week(self, load=True):
        t = date.today()
        self._set_dates(t - timedelta(days=t.weekday()), t, load)

    def _set_last_4_weeks(self, load=True):
        t = date.today()
        self._set_dates(t - timedelta(days=27), t, load)

    def _set_this_month(self, load=True):
        t = date.today()
        self._set_dates(t.replace(day=1), t, load)

    def _set_this_fy(self, load=True):
        s, e = fy_bounds()
        self._set_dates(s, min(e, date.today()), load)

    def _set_all_time(self, load=True):
        self._set_dates(date(2000, 1, 1), date.today(), load)

    # ── Data ──────────────────────────────────────────────────────────
    def _load(self):
        d_from = self.date_from.date().toPyDate()
        d_to   = self.date_to.date().toPyDate()
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        self._rows = report_ctrl.get_top_sellers(
            d_from, d_to,
            dept_id=self.dept_combo.currentData(),
            rank_by=self.rank_combo.currentData(),
            limit=self.limit_combo.currentData(),
            weighed_only=self.weighed_only.isChecked(),
        )

        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows, start=0):
            self.table.setItem(r, 0, _num_item(str(r + 1), r + 1, CENTER))
            self.table.setItem(r, 1, _text_item(row['plu']))
            self.table.setItem(r, 2, _text_item(row['item']))
            self.table.setItem(r, 3, _text_item(row['department_name']))
            self.table.setItem(r, 4, _num_item(f"{row['units']:,.0f}", row['units']))
            kg = row['weight_kg']
            self.table.setItem(r, 5, _num_item(f"{kg:,.1f}" if kg else "—", kg))
            self.table.setItem(r, 6, _text_item("Yes" if row['sold_by_weight'] else "No", CENTER))
            self.table.setItem(r, 7, _num_item(f"${row['sales_dollars']:,.2f}", row['sales_dollars']))
        self.table.setSortingEnabled(True)

        total_sales = sum(r['sales_dollars'] for r in self._rows)
        self.footer.setText(
            f"{len(self._rows)} items  |  ${total_sales:,.2f} sales shown  |  "
            f"{d_from:%d/%m/%Y} – {d_to:%d/%m/%Y}  |  "
            "Department comes from the product mapped to each PLU; "
            "unmapped PLUs show as 'Unmapped' and appear under All Departments only."
        )

    # ── Export ────────────────────────────────────────────────────────
    def _export(self):
        if not self._rows:
            QMessageBox.warning(self, "No Data", "Nothing to export — adjust the filters first.")
            return
        default = os.path.join(
            os.path.expanduser("~"), "Documents",
            f"Top_Sellers_{date.today():%Y%m%d}.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Top Sellers", default, "CSV Files (*.csv)")
        if not path:
            return
        try:
            self.write_csv(path)
            QMessageBox.information(self, "Exported", f"Top sellers saved to:\n{path}")
        except Exception as e:
            show_error(self, "Could not export top sellers.", e, title="Export Failed")

    def write_csv(self, path):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(["rank", "plu", "item", "department", "units_sold",
                        "weight_kg", "sold_by_weight", "sales_dollars"])
            for i, r in enumerate(self._rows, start=1):
                w.writerow([i, r['plu'], r['item'], r['department_name'],
                            f"{r['units']:.0f}", f"{r['weight_kg']:.1f}",
                            "Y" if r['sold_by_weight'] else "N",
                            f"{r['sales_dollars']:.2f}"])
