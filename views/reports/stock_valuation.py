import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QComboBox,
    QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import controllers.report_controller as report_ctrl
import csv, os


class NumItem(QTableWidgetItem):
    """Sorts numerically, stripping $ and commas."""
    def __lt__(self, other):
        try:
            return float(self.text().replace('$','').replace(',','')) < \
                   float(other.text().replace('$','').replace(',',''))
        except ValueError:
            return self.text() < other.text()


def _right(text, numeric=False):
    item = NumItem(str(text)) if numeric else QTableWidgetItem(str(text))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _make_table(headers, stretch_col=1):
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.setSortingEnabled(True)
    t.horizontalHeader().setSectionsClickable(True)
    return t


class StockValuationReport(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Department:"))
        self.dept_filter = QComboBox()
        self.dept_filter.addItem("All Departments", None)
        for d in report_ctrl.get_all_departments():
            self.dept_filter.addItem(d['name'], d['id'])
        self.dept_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.dept_filter)

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

    def _load(self):
        dept_id = self.dept_filter.currentData()
        mode = self.view_toggle.currentData()

        if mode == "summary":
            self.summary_table.show()
            self.detail_table.hide()
            self.summary_table.setSortingEnabled(False)
            rows = report_ctrl.get_stock_valuation_summary(dept_id)
            self.summary_table.setRowCount(0)
            total_cost = total_sell = 0
            for row in rows:
                r = self.summary_table.rowCount()
                self.summary_table.insertRow(r)
                self.summary_table.setItem(r, 0, QTableWidgetItem(row['dept_name'] or 'Unknown'))
                self.summary_table.setItem(r, 1, _right(str(row['product_count']), numeric=True))
                self.summary_table.setItem(r, 2, _right(f"{row['total_units']:.0f}", numeric=True))
                self.summary_table.setItem(r, 3, _right(f"${row['cost_value']:.2f}", numeric=True))
                self.summary_table.setItem(r, 4, _right(f"${row['sell_value']:.2f}", numeric=True))
                total_cost += row['cost_value'] or 0
                total_sell += row['sell_value'] or 0
            self.summary_table.setSortingEnabled(True)
            self.total_label.setText(
                f"<b>Total Cost Value: ${total_cost:,.2f}</b> &nbsp;&nbsp; "
                f"<b>Total Sell Value: ${total_sell:,.2f}</b>"
            )
        else:
            self.summary_table.hide()
            self.detail_table.show()
            self.detail_table.setSortingEnabled(False)
            rows = report_ctrl.get_stock_valuation_detail(dept_id)
            self.detail_table.setRowCount(0)
            total_cost = total_sell = 0
            for row in rows:
                r = self.detail_table.rowCount()
                self.detail_table.insertRow(r)
                self.detail_table.setItem(r, 0, QTableWidgetItem(row['barcode']))
                self.detail_table.setItem(r, 1, QTableWidgetItem(row['description']))
                self.detail_table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))
                self.detail_table.setItem(r, 3, QTableWidgetItem(row['unit'] or ''))
                self.detail_table.setItem(r, 4, _right(f"{row['quantity']:.0f}", numeric=True))
                self.detail_table.setItem(r, 5, _right(f"${row['cost_value']:.2f}", numeric=True))
                self.detail_table.setItem(r, 6, _right(f"${row['sell_value']:.2f}", numeric=True))
                total_cost += row['cost_value'] or 0
                total_sell += row['sell_value'] or 0
            self.detail_table.setSortingEnabled(True)
            self.total_label.setText(
                f"<b>Total Cost Value: ${total_cost:,.2f}</b> &nbsp;&nbsp; "
                f"<b>Total Sell Value: ${total_sell:,.2f}</b>"
            )

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join(os.path.expanduser("~/Downloads"), "stock_valuation.csv"), "CSV (*.csv)")
        if not path:
            return
        dept_id = self.dept_filter.currentData()
        rows = report_ctrl.get_stock_valuation_detail(dept_id)
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Barcode", "Description", "Department", "Unit", "Qty", "Cost Value", "Sell Value"])
            for row in rows:
                w.writerow([f'="{row["barcode"]}"', row['description'], row['dept_name'],
                             row['unit'], row['quantity'], row['cost_value'], row['sell_value']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
