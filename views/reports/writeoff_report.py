import os
import csv
from datetime import date, timedelta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QDateEdit, QTabWidget,
    QFileDialog, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
import controllers.report_controller as report_ctrl
from utils.error_dialog import show_error

SPOILAGE_TYPES  = ['OD - Out of Date']
SHRINKAGE_TYPES = ['IS - Incorrectly Sold', 'NS - Not on Shelf', 'DG', 'SE - Stocktake Error']
ADMIN_TYPES     = ['IE - Invoice Error']

def _category(movement_type):
    if movement_type in SPOILAGE_TYPES:
        return 'Spoilage'
    if movement_type in SHRINKAGE_TYPES:
        return 'Shrinkage'
    if movement_type in ADMIN_TYPES:
        return 'Admin'
    return 'Other'


class NumItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text().replace('$','').replace(',','')) < \
                   float(other.text().replace('$','').replace(',',''))
        except ValueError:
            return super().__lt__(other)

class WriteOffReport(QWidget):
    def __init__(self):
        super().__init__()
        self._last_rows = []
        self._build_ui()
        self._set_this_month()

    def showEvent(self, event):
        super().showEvent(event)
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("Write-Off Report")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        cost_note = QLabel("⚠  Cost values based on current product cost price (ex. GST)")
        cost_note.setStyleSheet("color: #FF9800; font-size: 11px;")
        layout.addWidget(cost_note)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setMinimumHeight(32)
        filter_row.addWidget(self.date_from)
        filter_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setMinimumHeight(32)
        filter_row.addWidget(self.date_to)

        btn_style = (
            "QPushButton{background:#1e2a38;color:#e6edf3;border:1px solid #2a3a4a;"
            "border-radius:3px;padding:0 10px;font-size:11px;height:30px;}"
            "QPushButton:hover{background:#2a3a4a;}"
        )
        for label, fn in [("This Month", self._set_this_month),
                           ("Last Month", self._set_last_month),
                           ("This FY",    self._set_this_fy)]:
            btn = QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(fn)
            filter_row.addWidget(btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #2a3a4a;")
        filter_row.addWidget(sep)

        filter_row.addWidget(QLabel("Category:"))
        self.cat_filter = QComboBox()
        self.cat_filter.addItem("All Write-Offs", None)
        self.cat_filter.addItem("🟠 Spoilage", "Spoilage")
        self.cat_filter.addItem("🔴 Shrinkage", "Shrinkage")
        self.cat_filter.addItem("🔵 Admin", "Admin")
        self.cat_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.cat_filter)

        filter_row.addWidget(QLabel("Department:"))
        self.dept_filter = QComboBox()
        self.dept_filter.addItem("All Departments", None)
        for d in report_ctrl.get_all_departments():
            self.dept_filter.addItem(d['name'], d['id'])
        self.dept_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.dept_filter)

        apply_btn = QPushButton("Apply")
        apply_btn.setMinimumHeight(32)
        apply_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:0 16px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        apply_btn.clicked.connect(self._load)
        filter_row.addWidget(apply_btn)
        filter_row.addStretch()
        btn_export = QPushButton("⬇ Export CSV")
        btn_export.setMinimumHeight(32)
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)
        layout.addLayout(filter_row)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.card_total_units = self._make_card("Total Units", "0", "#e6edf3")
        self.card_total_value = self._make_card("Total Cost Value", "$0.00", "#f85149")
        self.card_spoilage    = self._make_card("Spoilage", "0 units", "#FF9800")
        self.card_shrinkage   = self._make_card("Shrinkage", "0 units", "#f85149")
        self.card_admin       = self._make_card("Admin Corrections", "0 units", "#5c9de8")
        for card in [self.card_total_units, self.card_total_value,
                     self.card_spoilage, self.card_shrinkage, self.card_admin]:
            cards_row.addWidget(card[0])
        layout.addLayout(cards_row)

        self.tabs = QTabWidget()

        self.item_table = QTableWidget()
        self.item_table.setColumnCount(9)
        self.item_table.setHorizontalHeaderLabels([
            "Date", "Barcode", "Description", "Department",
            "Supplier", "Type", "Category", "Units", "Cost Value"
        ])
        self.item_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.item_table.setColumnWidth(0, 130)
        self.item_table.setColumnWidth(1, 120)
        self.item_table.setColumnWidth(3,  90)
        self.item_table.setColumnWidth(4, 110)
        self.item_table.setColumnWidth(5, 160)
        self.item_table.setColumnWidth(6,  80)
        self.item_table.setColumnWidth(7,  60)
        self.item_table.setColumnWidth(8,  90)
        self.item_table.setSortingEnabled(True)
        self.item_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.item_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.item_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.item_table, "📋 By Item")

        self.type_table = QTableWidget()
        self.type_table.setColumnCount(5)
        self.type_table.setHorizontalHeaderLabels([
            "Type", "Category", "Incidents", "Total Units", "Cost Value"
        ])
        self.type_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.type_table.setSortingEnabled(True)
        self.type_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.type_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.type_table, "📊 By Type")

        layout.addWidget(self.tabs)
        self.footer = QLabel("")
        self.footer.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self.footer)

    def _make_card(self, title, value, color):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame{background:#1e2a38;border:1px solid #2a3a4a;border-radius:6px;}"
        )
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(12, 8, 12, 8)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #8b949e; font-size: 11px;")
        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: bold;")
        card_layout.addWidget(lbl_title)
        card_layout.addWidget(lbl_val)
        return frame, lbl_val

    def _load(self):
        d_from   = self.date_from.date().toPyDate()
        d_to     = self.date_to.date().toPyDate()
        dept_id  = self.dept_filter.currentData()
        category = self.cat_filter.currentData()
        rows = report_ctrl.get_writeoff_data(d_from, d_to, dept_id, category)

        total_units = 0
        total_value = 0.0
        spoilage_u  = 0
        shrinkage_u = 0
        admin_u     = 0
        type_summary = {}

        self.item_table.setSortingEnabled(False)
        self.item_table.setRowCount(0)

        for row in rows:
            units = abs(int(row['quantity']))
            cost  = float(row['cost_price']) if row['cost_price'] else 0.0
            value = units * cost
            cat   = _category(row['movement_type'])

            total_units += units
            total_value += value
            if cat == 'Spoilage':   spoilage_u  += units
            elif cat == 'Shrinkage': shrinkage_u += units
            elif cat == 'Admin':     admin_u     += units

            t = row['movement_type']
            if t not in type_summary:
                type_summary[t] = {'cat': cat, 'incidents': 0, 'units': 0, 'value': 0.0}
            type_summary[t]['incidents'] += 1
            type_summary[t]['units']     += units
            type_summary[t]['value']     += value

            r = self.item_table.rowCount()
            self.item_table.insertRow(r)
            cat_color = {'Spoilage': '#FF9800', 'Shrinkage': '#f85149', 'Admin': '#5c9de8'}.get(cat, '#8b949e')

            self.item_table.setItem(r, 0, QTableWidgetItem(str(row['created_at'])[:16]))
            self.item_table.setItem(r, 1, QTableWidgetItem(row['barcode']))
            self.item_table.setItem(r, 2, QTableWidgetItem(row['description'] or ''))
            self.item_table.setItem(r, 3, QTableWidgetItem(row['dept_name'] or ''))
            self.item_table.setItem(r, 4, QTableWidgetItem(row['supplier_name'] or ''))
            self.item_table.setItem(r, 5, QTableWidgetItem(row['movement_type']))
            cat_item = QTableWidgetItem(cat)
            cat_item.setForeground(QColor(cat_color))
            self.item_table.setItem(r, 6, cat_item)
            u_item = NumItem(str(units))
            u_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.item_table.setItem(r, 7, u_item)
            v_item = NumItem(f"${value:.2f}")
            v_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            v_item.setForeground(QColor('#f85149') if value > 0 else QColor('#8b949e'))
            self.item_table.setItem(r, 8, v_item)

        self.item_table.setSortingEnabled(True)

        self.type_table.setSortingEnabled(False)
        self.type_table.setRowCount(0)
        for t, data in sorted(type_summary.items(), key=lambda x: -x[1]['value']):
            r = self.type_table.rowCount()
            self.type_table.insertRow(r)
            cat_color = {'Spoilage': '#FF9800', 'Shrinkage': '#f85149', 'Admin': '#5c9de8'}.get(data['cat'], '#8b949e')
            self.type_table.setItem(r, 0, QTableWidgetItem(t))
            ci = QTableWidgetItem(data['cat'])
            ci.setForeground(QColor(cat_color))
            self.type_table.setItem(r, 1, ci)
            ii = NumItem(str(data['incidents']))
            ii.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.type_table.setItem(r, 2, ii)
            ui = NumItem(str(data['units']))
            ui.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.type_table.setItem(r, 3, ui)
            vi = NumItem(f"${data['value']:.2f}")
            vi.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            vi.setForeground(QColor('#f85149'))
            self.type_table.setItem(r, 4, vi)
        self.type_table.setSortingEnabled(True)

        self.card_total_units[1].setText(str(total_units))
        self.card_total_value[1].setText(f"${total_value:.2f}")
        self.card_spoilage[1].setText(f"{spoilage_u} units")
        self.card_shrinkage[1].setText(f"{shrinkage_u} units")
        self.card_admin[1].setText(f"{admin_u} units")

        period = f"{d_from.strftime('%d/%m/%Y')} – {d_to.strftime('%d/%m/%Y')}"
        self.footer.setText(
            f"Period: {period}  |  {len(rows)} records  |  "
            f"{total_units} units  |  Total cost value: ${total_value:.2f}"
        )
        self._last_rows = rows

    def _set_dates(self, d_from, d_to):
        self.date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self.date_to.setDate(QDate(d_to.year, d_to.month, d_to.day))
        self._load()

    def _set_this_month(self):
        t = date.today()
        self._set_dates(t.replace(day=1), t)

    def _set_last_month(self):
        t = date.today()
        last = t.replace(day=1) - timedelta(days=1)
        self._set_dates(last.replace(day=1), last)

    def _set_this_fy(self):
        t = date.today()
        y = t.year if t.month >= 7 else t.year - 1
        self._set_dates(date(y, 7, 1), t)

    def _export(self):
        if not self._last_rows:
            QMessageBox.information(self, "No Data", "Nothing to export.")
            return
        default = os.path.join(
            os.path.expanduser("~"), "Documents",
            f"WriteOff_Report_{date.today().strftime('%Y%m%d')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Export Write-Off Report", default, "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["Date", "Barcode", "Description", "Department",
                             "Supplier", "Type", "Category", "Units", "Cost Value"])
                for row in self._last_rows:
                    units = abs(int(row['quantity']))
                    cost  = float(row['cost_price']) if row['cost_price'] else 0.0
                    value = units * cost
                    w.writerow([str(row['created_at'])[:16], f'="{row["barcode"]}"',
                                row['description'] or '', row['dept_name'] or '',
                                row['supplier_name'] or '', row['movement_type'],
                                _category(row['movement_type']), units, f"${value:.2f}"])
            QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
        except Exception as e:
            show_error(self, "Could not export write-off report.", e, title="Export Failed")
