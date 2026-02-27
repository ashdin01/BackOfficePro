from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from database.connection import get_connection
import csv


def get_gp_data(dept_id=None, gp_filter="all"):
    conn = get_connection()
    sql = """
        SELECT p.barcode, p.description, d.name as dept_name,
               p.sell_price, p.cost_price,
               CASE WHEN p.sell_price > 0
                    THEN ROUND((1.0 - p.cost_price / p.sell_price) * 100, 1)
                    ELSE 0 END as gp_pct,
               p.sell_price - p.cost_price as gp_dollars
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1 AND p.sell_price > 0
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    if gp_filter == "healthy":
        sql += " AND (1.0 - p.cost_price / p.sell_price) * 100 >= 30"
    elif gp_filter == "marginal":
        sql += " AND (1.0 - p.cost_price / p.sell_price) * 100 >= 15 AND (1.0 - p.cost_price / p.sell_price) * 100 < 30"
    elif gp_filter == "low":
        sql += " AND (1.0 - p.cost_price / p.sell_price) * 100 < 15"
    sql += " ORDER BY gp_pct ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_gp_summary(dept_id=None):
    conn = get_connection()
    sql = """
        SELECT d.name as dept_name,
               COUNT(*) as product_count,
               ROUND(AVG(CASE WHEN p.sell_price > 0
                    THEN (1.0 - p.cost_price / p.sell_price) * 100
                    ELSE 0 END), 1) as avg_gp,
               SUM(CASE WHEN (1.0 - p.cost_price/p.sell_price)*100 >= 30 THEN 1 ELSE 0 END) as healthy,
               SUM(CASE WHEN (1.0 - p.cost_price/p.sell_price)*100 >= 15
                         AND (1.0 - p.cost_price/p.sell_price)*100 < 30 THEN 1 ELSE 0 END) as marginal,
               SUM(CASE WHEN (1.0 - p.cost_price/p.sell_price)*100 < 15 THEN 1 ELSE 0 END) as low_gp
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        WHERE p.active = 1 AND p.sell_price > 0
    """
    params = []
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    sql += " GROUP BY d.name ORDER BY avg_gp ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_departments():
    conn = get_connection()
    rows = conn.execute("SELECT id, name FROM departments WHERE active=1 ORDER BY name").fetchall()
    conn.close()
    return rows


class GPReport(QWidget):
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

        filter_row.addWidget(QLabel("GP Filter:"))
        self.gp_filter = QComboBox()
        self.gp_filter.addItem("All Products", "all")
        self.gp_filter.addItem("✓ Healthy (≥30%)", "healthy")
        self.gp_filter.addItem("⚠ Marginal (15–30%)", "marginal")
        self.gp_filter.addItem("✕ Low GP (<15%)", "low")
        self.gp_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.gp_filter)

        self.view_toggle = QComboBox()
        self.view_toggle.addItem("Detail View", "detail")
        self.view_toggle.addItem("Summary by Department", "summary")
        self.view_toggle.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.view_toggle)

        filter_row.addStretch()
        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)
        layout.addLayout(filter_row)

        # Detail table
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(6)
        self.detail_table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department",
            "Sell Price", "Cost Price", "GP %"
        ])
        self.detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.detail_table)

        # Summary table
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels([
            "Department", "Products", "Avg GP %", "✓ Healthy", "⚠ Marginal", "✕ Low"
        ])
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.hide()
        layout.addWidget(self.summary_table)

        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        footer.addWidget(self.status_label)
        layout.addLayout(footer)

    def _load(self):
        dept_id = self.dept_filter.currentData()
        gp_filter = self.gp_filter.currentData()
        mode = self.view_toggle.currentData()

        if mode == "summary":
            self.detail_table.hide()
            self.summary_table.show()
            rows = get_gp_summary(dept_id)
            self.summary_table.setRowCount(0)
            for row in rows:
                r = self.summary_table.rowCount()
                self.summary_table.insertRow(r)
                self.summary_table.setItem(r, 0, QTableWidgetItem(row['dept_name'] or ''))
                self._center(self.summary_table, r, 1, str(row['product_count']))
                avg = row['avg_gp'] or 0
                avg_item = QTableWidgetItem(f"{avg:.1f}%")
                avg_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                avg_item.setForeground(
                    QColor("green") if avg >= 30 else QColor("orange") if avg >= 15 else QColor("red")
                )
                self.summary_table.setItem(r, 2, avg_item)
                self._center(self.summary_table, r, 3, str(row['healthy']))
                self._center(self.summary_table, r, 4, str(row['marginal']))
                self._center(self.summary_table, r, 5, str(row['low_gp']))
            self.status_label.setText(f"{len(rows)} departments")
        else:
            self.summary_table.hide()
            self.detail_table.show()
            rows = get_gp_data(dept_id, gp_filter)
            self.detail_table.setRowCount(0)
            low_count = marginal_count = healthy_count = 0
            for row in rows:
                r = self.detail_table.rowCount()
                self.detail_table.insertRow(r)
                gp = row['gp_pct'] or 0
                if gp >= 30:
                    color = QColor("green")
                    healthy_count += 1
                elif gp >= 15:
                    color = QColor("orange")
                    marginal_count += 1
                else:
                    color = QColor("red")
                    low_count += 1
                self.detail_table.setItem(r, 0, QTableWidgetItem(row['barcode']))
                self.detail_table.setItem(r, 1, QTableWidgetItem(row['description']))
                self.detail_table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))
                self._right(self.detail_table, r, 3, f"${row['sell_price']:.2f}")
                self._right(self.detail_table, r, 4, f"${row['cost_price']:.2f}")
                gp_item = QTableWidgetItem(f"{gp:.1f}%")
                gp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                gp_item.setForeground(color)
                self.detail_table.setItem(r, 5, gp_item)
            self.status_label.setText(
                f"{self.detail_table.rowCount()} products — "
                f"<span style='color:green'>✓ {healthy_count} healthy</span>  "
                f"<span style='color:orange'>⚠ {marginal_count} marginal</span>  "
                f"<span style='color:red'>✕ {low_count} low</span>"
            )

    def _center(self, table, row, col, text):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, col, item)

    def _right(self, table, row, col, text):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, col, item)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "gp_report.csv", "CSV (*.csv)")
        if not path:
            return
        rows = get_gp_data(self.dept_filter.currentData(), self.gp_filter.currentData())
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Barcode", "Description", "Department", "Sell Price", "Cost Price", "GP %"])
            for row in rows:
                w.writerow([row['barcode'], row['description'], row['dept_name'],
                             row['sell_price'], row['cost_price'], row['gp_pct']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
