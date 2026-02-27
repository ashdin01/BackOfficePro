from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from database.connection import get_connection
import csv, os
from PyQt6.QtWidgets import QFileDialog, QMessageBox


def get_valuation(dept_id=None):
    conn = get_connection()
    sql = """
        SELECT d.name as dept_name,
               COUNT(p.barcode) as product_count,
               SUM(COALESCE(s.quantity,0)) as total_units,
               SUM(COALESCE(s.quantity,0) * p.cost_price) as cost_value,
               SUM(COALESCE(s.quantity,0) * p.sell_price) as sell_value
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    sql += " GROUP BY d.name ORDER BY d.name"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_valuation_detail(dept_id=None):
    conn = get_connection()
    sql = """
        SELECT p.barcode, p.description, d.name as dept_name,
               p.unit, p.cost_price, p.sell_price,
               COALESCE(s.quantity,0) as quantity,
               COALESCE(s.quantity,0) * p.cost_price as cost_value,
               COALESCE(s.quantity,0) * p.sell_price as sell_value
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    sql += " ORDER BY d.name, p.description"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_departments():
    conn = get_connection()
    rows = conn.execute("SELECT id, name FROM departments WHERE active=1 ORDER BY name").fetchall()
    conn.close()
    return rows


class StockValuationReport(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Filters
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Department:"))
        self.dept_filter = QComboBox()
        self.dept_filter.addItem("All Departments", None)
        for d in get_departments():
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

        # Summary table
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(5)
        self.summary_table.setHorizontalHeaderLabels([
            "Department", "Products", "Total Units", "Cost Value", "Sell Value"
        ])
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.summary_table)

        # Detail table (hidden by default)
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(7)
        self.detail_table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department", "Unit",
            "Qty", "Cost Value", "Sell Value"
        ])
        self.detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.hide()
        layout.addWidget(self.detail_table)

        # Footer totals
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
            rows = get_valuation(dept_id)
            self.summary_table.setRowCount(0)
            total_cost = total_sell = 0
            for row in rows:
                r = self.summary_table.rowCount()
                self.summary_table.insertRow(r)
                self.summary_table.setItem(r, 0, QTableWidgetItem(row['dept_name'] or 'Unknown'))
                self._right(self.summary_table, r, 1, str(row['product_count']))
                self._right(self.summary_table, r, 2, f"{row['total_units']:.0f}")
                self._right(self.summary_table, r, 3, f"${row['cost_value']:.2f}")
                self._right(self.summary_table, r, 4, f"${row['sell_value']:.2f}")
                total_cost += row['cost_value'] or 0
                total_sell += row['sell_value'] or 0
            self.total_label.setText(
                f"<b>Total Cost Value: ${total_cost:,.2f}</b> &nbsp;&nbsp; "
                f"<b>Total Sell Value: ${total_sell:,.2f}</b>"
            )
        else:
            self.summary_table.hide()
            self.detail_table.show()
            rows = get_valuation_detail(dept_id)
            self.detail_table.setRowCount(0)
            total_cost = total_sell = 0
            for row in rows:
                r = self.detail_table.rowCount()
                self.detail_table.insertRow(r)
                self.detail_table.setItem(r, 0, QTableWidgetItem(row['barcode']))
                self.detail_table.setItem(r, 1, QTableWidgetItem(row['description']))
                self.detail_table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))
                self.detail_table.setItem(r, 3, QTableWidgetItem(row['unit'] or ''))
                self._right(self.detail_table, r, 4, f"{row['quantity']:.0f}")
                self._right(self.detail_table, r, 5, f"${row['cost_value']:.2f}")
                self._right(self.detail_table, r, 6, f"${row['sell_value']:.2f}")
                total_cost += row['cost_value'] or 0
                total_sell += row['sell_value'] or 0
            self.total_label.setText(
                f"<b>Total Cost Value: ${total_cost:,.2f}</b> &nbsp;&nbsp; "
                f"<b>Total Sell Value: ${total_sell:,.2f}</b>"
            )

    def _right(self, table, row, col, text):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, col, item)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "stock_valuation.csv", "CSV (*.csv)")
        if not path:
            return
        dept_id = self.dept_filter.currentData()
        rows = get_valuation_detail(dept_id)
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Barcode", "Description", "Department", "Unit", "Qty", "Cost Value", "Sell Value"])
            for row in rows:
                w.writerow([row['barcode'], row['description'], row['dept_name'],
                             row['unit'], row['quantity'], row['cost_value'], row['sell_value']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
