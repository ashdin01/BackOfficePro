import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from database.connection import get_connection

class NumItem(QTableWidgetItem):
    """Sorts numerically, stripping $, %, commas and +/-."""
    def __lt__(self, other):
        def _val(t):
            try:
                return float(t.replace('$','').replace('%','').replace(',','').replace('+','').strip())
            except ValueError:
                return t
        return _val(self.text()) < _val(other.text())


import csv


def get_reorder_items(dept_id=None, supplier_id=None):
    conn = get_connection()
    sql = """
        SELECT p.barcode, p.description, d.name as dept_name,
               sup.name as supplier_name,
               COALESCE(s.quantity, 0) as on_hand,
               p.reorder_point,
               COALESCE(p.reorder_max, 0) as reorder_max,
               p.unit, p.cost_price,
               CASE
                   WHEN COALESCE(p.reorder_max, 0) > 0
                   THEN MAX(1, COALESCE(p.reorder_max, 0) - COALESCE(s.quantity, 0))
                   ELSE 0
               END as suggested_qty,
               CASE
                   WHEN COALESCE(p.reorder_max, 0) > 0
                   THEN MAX(1, COALESCE(p.reorder_max, 0) - COALESCE(s.quantity, 0)) * p.cost_price
                   ELSE 0
               END as order_cost
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        LEFT JOIN departments d ON p.department_id = d.id
        LEFT JOIN suppliers sup ON p.supplier_id = sup.id
        WHERE p.active = 1
          AND COALESCE(s.quantity, 0) <= p.reorder_point
          AND p.reorder_point > 0
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    if supplier_id:
        sql += " AND p.supplier_id = ?"
        params.append(supplier_id)
    sql += " ORDER BY sup.name, d.name, p.description"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_departments():
    conn = get_connection()
    rows = conn.execute("SELECT id, name FROM departments WHERE active=1 ORDER BY name").fetchall()
    conn.close()
    return rows


def get_suppliers():
    conn = get_connection()
    rows = conn.execute("SELECT id, name FROM suppliers WHERE active=1 ORDER BY name").fetchall()
    conn.close()
    return rows


class ReorderReport(QWidget):
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
        for d in get_departments():
            self.dept_filter.addItem(d['name'], d['id'])
        self.dept_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.dept_filter)

        filter_row.addWidget(QLabel("Supplier:"))
        self.sup_filter = QComboBox()
        self.sup_filter.addItem("All Suppliers", None)
        for s in get_suppliers():
            self.sup_filter.addItem(s['name'], s['id'])
        self.sup_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.sup_filter)

        filter_row.addStretch()
        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)
        layout.addLayout(filter_row)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department", "Supplier",
            "On Hand", "Reorder Pt", "Order Qty", "Unit Cost", "Order Cost"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionsClickable(True)
        layout.addWidget(self.table)

        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.cost_label = QLabel("")
        self.cost_label.setTextFormat(Qt.TextFormat.RichText)
        footer.addWidget(self.status_label)
        footer.addStretch()
        footer.addWidget(self.cost_label)
        layout.addLayout(footer)

    def _load(self):
        dept_id = self.dept_filter.currentData()
        sup_id = self.sup_filter.currentData()
        rows = get_reorder_items(dept_id, sup_id)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        total_cost = 0

        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            on_hand = row['on_hand']
            reorder = row['reorder_point']

            self.table.setItem(r, 0, QTableWidgetItem(row['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(row['description']))
            self.table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))
            self.table.setItem(r, 3, QTableWidgetItem(row['supplier_name'] or ''))

            qty_item = NumItem(f"{on_hand:.0f}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_item.setForeground(QColor("red") if on_hand == 0 else QColor("orange"))
            self.table.setItem(r, 4, qty_item)

            self._center(r, 5, f"{reorder:.0f}")
            self._right(r, 7, f"${row['cost_price']:.2f}")
            self._right(r, 8, f"${row['order_cost']:.2f}")
            total_cost += row['order_cost'] or 0

        self.table.setSortingEnabled(True)
        self.status_label.setText(f"{self.table.rowCount()} items need reordering")
        self.cost_label.setText(f"<b>Estimated Order Cost: ${total_cost:,.2f}</b>")

    def _center(self, row, col, text):
        item = NumItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, col, item)

    def _right(self, row, col, text):
        item = NumItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, col, item)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join(os.path.expanduser("~/Downloads"), "reorder_report.csv"), "CSV (*.csv)")
        if not path:
            return
        rows = get_reorder_items(self.dept_filter.currentData(), self.sup_filter.currentData())
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Barcode", "Description", "Department", "Supplier",
                        "On Hand", "Reorder Point", "Order Qty", "Unit Cost", "Order Cost"])
            for row in rows:
                w.writerow([row['barcode'], row['description'], row['dept_name'],
                             row['supplier_name'], row['on_hand'], row['reorder_point'],
                             row['cost_price'], row['order_cost']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
