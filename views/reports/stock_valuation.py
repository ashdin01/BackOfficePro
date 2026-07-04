import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QComboBox,
    QFileDialog, QMessageBox, QCheckBox,
    QDateEdit
)
from PyQt6.QtCore import Qt, QDate
import config.styles as styles
import controllers.report_controller as report_ctrl
from views.base_view import BaseView
from views.widgets.table_items import right_item as _right
from views.widgets.table_utils import make_table as _make_table_base
import csv, os


def _make_table(headers, stretch_col=1):
    t = _make_table_base(headers, stretch_col)
    t.horizontalHeader().setSectionsClickable(True)
    return t


class _DeptMultiSelect(QWidget):
    """Checkbox list of departments, shown as a borderless popup under a filter button.

    Uses Qt.WindowType.Popup directly rather than QMenu + QWidgetAction — the
    native Windows style ('windowsvista') is known to fail to paint custom
    widgets embedded in a QMenu, leaving the checkboxes invisible even though
    they're present. A plain Popup window sidesteps that entirely and still
    auto-closes on outside click / Escape like a normal dropdown.
    """

    def __init__(self, departments, on_change, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setStyleSheet(
            f"background:{styles.CLR_BG_PANEL}; border:1px solid {styles.CLR_BORDER};"
        )
        self._on_change = on_change
        self._boxes = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        select_row = QHBoxLayout()
        all_btn = QPushButton("All")
        none_btn = QPushButton("None")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn.clicked.connect(lambda: self._set_all(False))
        select_row.addWidget(all_btn)
        select_row.addWidget(none_btn)
        layout.addLayout(select_row)

        for d in departments:
            cb = QCheckBox(d['name'])
            cb.setChecked(True)
            cb.setProperty("dept_id", d['id'])
            cb.stateChanged.connect(self._on_change)
            layout.addWidget(cb)
            self._boxes.append(cb)

    def _set_all(self, checked):
        for cb in self._boxes:
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self._on_change()

    def selected_ids(self):
        return [cb.property("dept_id") for cb in self._boxes if cb.isChecked()]

    def is_all_selected(self):
        return all(cb.isChecked() for cb in self._boxes)

    def summary_text(self):
        total = len(self._boxes)
        checked = sum(cb.isChecked() for cb in self._boxes)
        if checked == total:
            return "All Departments"
        if checked == 0:
            return "No Departments"
        return f"{checked} of {total} Departments"

    def show_below(self, anchor_widget):
        pos = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        self.move(pos)
        self.show()


class StockValuationReport(BaseView):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Department:"))

        depts = report_ctrl.get_all_departments()
        self.dept_select = _DeptMultiSelect(depts, on_change=self._on_dept_change, parent=self)

        self.dept_btn = QPushButton("All Departments ▾")
        self.dept_btn.clicked.connect(lambda: self.dept_select.show_below(self.dept_btn))
        filter_row.addWidget(self.dept_btn)

        filter_row.addWidget(QLabel("As of:"))
        self.as_of_date = QDateEdit()
        self.as_of_date.setCalendarPopup(True)
        self.as_of_date.setDisplayFormat("dd/MM/yyyy")
        self.as_of_date.setMaximumDate(QDate.currentDate())
        self.as_of_date.setDate(QDate.currentDate())
        self.as_of_date.dateChanged.connect(self._load)
        filter_row.addWidget(self.as_of_date)

        self.view_toggle = QComboBox()
        self.view_toggle.addItem("Summary by Department", "summary")
        self.view_toggle.addItem("Full Detail", "detail")
        self.view_toggle.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.view_toggle)

        filter_row.addStretch()
        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)
        layout.addLayout(filter_row)

        self.summary_table = _make_table(
            ["Department", "Products", "Total Units", "Cost Value", "Sell Value"],
            stretch_col=0
        )
        layout.addWidget(self.summary_table)

        self.detail_table = _make_table(
            ["Barcode", "Description", "Department", "Unit", "Qty", "Cost Value", "Sell Value"],
            stretch_col=1
        )
        self.detail_table.hide()
        layout.addWidget(self.detail_table)

        footer = QHBoxLayout()
        self.total_label = QLabel("")
        self.total_label.setTextFormat(Qt.TextFormat.RichText)
        footer.addStretch()
        footer.addWidget(self.total_label)
        layout.addLayout(footer)

    def _on_dept_change(self, *_):
        self.dept_btn.setText(f"{self.dept_select.summary_text()} ▾")
        self._load()

    def _selected_dept_ids(self):
        return None if self.dept_select.is_all_selected() else self.dept_select.selected_ids()

    def _selected_as_of_date(self):
        """Returns None for 'today' (live SOH), else 'YYYY-MM-DD'."""
        d = self.as_of_date.date()
        if d == QDate.currentDate():
            return None
        return d.toString("yyyy-MM-dd")

    def _load(self):
        dept_ids = self._selected_dept_ids()
        as_of_date = self._selected_as_of_date()
        mode = self.view_toggle.currentData()

        as_of_note = f" (as of {self.as_of_date.date().toString('dd/MM/yyyy')})" if as_of_date else ""

        if mode == "summary":
            self.summary_table.show()
            self.detail_table.hide()
            self.summary_table.setSortingEnabled(False)
            rows = report_ctrl.get_stock_valuation_summary(dept_ids, as_of_date)
            self.summary_table.setRowCount(0)
            total_cost = total_sell = 0
            for row in rows:
                r = self.summary_table.rowCount()
                self.summary_table.insertRow(r)
                self.summary_table.setItem(r, 0, QTableWidgetItem(row['dept_name'] or 'Unknown'))
                self.summary_table.setItem(r, 1, _right(str(int(row['product_count'] or 0))))
                self.summary_table.setItem(r, 2, _right(f"{row['total_units'] or 0:.2f}"))
                self.summary_table.setItem(r, 3, _right(f"${row['cost_value'] or 0:,.2f}"))
                self.summary_table.setItem(r, 4, _right(f"${row['sell_value'] or 0:,.2f}"))
                total_cost += row['cost_value'] or 0
                total_sell += row['sell_value'] or 0
            self.summary_table.setSortingEnabled(True)
            self.total_label.setText(
                f"<b>Total Cost Value: ${total_cost:,.2f}</b> &nbsp;&nbsp; "
                f"<b>Total Sell Value: ${total_sell:,.2f}</b>{as_of_note}"
            )
        else:
            self.summary_table.hide()
            self.detail_table.show()
            self.detail_table.setSortingEnabled(False)
            rows = report_ctrl.get_stock_valuation_detail(dept_ids, as_of_date)
            self.detail_table.setRowCount(0)
            total_cost = total_sell = 0
            for row in rows:
                r = self.detail_table.rowCount()
                self.detail_table.insertRow(r)
                self.detail_table.setItem(r, 0, QTableWidgetItem(row['barcode']))
                self.detail_table.setItem(r, 1, QTableWidgetItem(row['description']))
                self.detail_table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))
                self.detail_table.setItem(r, 3, QTableWidgetItem(row['unit'] or ''))
                self.detail_table.setItem(r, 4, _right(f"{row['quantity'] or 0:.2f}"))
                self.detail_table.setItem(r, 5, _right(f"${row['cost_value'] or 0:,.2f}"))
                self.detail_table.setItem(r, 6, _right(f"${row['sell_value'] or 0:,.2f}"))
                total_cost += row['cost_value'] or 0
                total_sell += row['sell_value'] or 0
            self.detail_table.setSortingEnabled(True)
            self.total_label.setText(
                f"<b>Total Cost Value: ${total_cost:,.2f}</b> &nbsp;&nbsp; "
                f"<b>Total Sell Value: ${total_sell:,.2f}</b>{as_of_note}"
            )

    def _export(self):
        as_of_date = self._selected_as_of_date()
        default_name = f"stock_valuation_{as_of_date or 'current'}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join(os.path.expanduser("~/Downloads"), default_name), "CSV (*.csv)")
        if not path:
            return
        dept_ids = self._selected_dept_ids()
        rows = report_ctrl.get_stock_valuation_detail(dept_ids, as_of_date)
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Barcode", "Description", "Department", "Unit", "Qty", "Cost Value", "Sell Value"])
            for row in rows:
                w.writerow([row['barcode'], row['description'], row['dept_name'],
                             row['unit'], row['quantity'], row['cost_value'], row['sell_value']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
