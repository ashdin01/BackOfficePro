import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import controllers.report_controller as report_ctrl

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
        for d in report_ctrl.get_all_departments():
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
        self.detail_table.setSortingEnabled(True)
        self.detail_table.horizontalHeader().setSectionsClickable(True)
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.detail_table.doubleClicked.connect(self._open_product)
        self.detail_table.setToolTip('Double-click a row to open product detail')
        layout.addWidget(self.detail_table)

        # Summary table
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels([
            "Department", "Products", "Avg GP %", "✓ Healthy", "⚠ Marginal", "✕ Low"
        ])
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.summary_table.setSortingEnabled(True)
        self.summary_table.horizontalHeader().setSectionsClickable(True)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.hide()
        layout.addWidget(self.summary_table)

        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        footer.addWidget(self.status_label)
        layout.addLayout(footer)

    def _open_product(self, index):
        row = index.row()
        barcode_item = self.detail_table.item(row, 0)
        if not barcode_item:
            return
        barcode = barcode_item.text().strip()
        if not barcode:
            return
        from views.products.product_edit import ProductEdit
        self._product_win = ProductEdit(barcode=barcode, on_save=self._load)
        self._product_win.show()
        self._product_win.raise_()

    def _load(self):
        dept_id = self.dept_filter.currentData()
        gp_filter = self.gp_filter.currentData()
        mode = self.view_toggle.currentData()

        if mode == "summary":
            self.detail_table.hide()
            self.summary_table.show()
            rows = report_ctrl.get_gp_summary(dept_id)
            self.summary_table.setSortingEnabled(False)
            self.summary_table.setRowCount(0)
            for row in rows:
                r = self.summary_table.rowCount()
                self.summary_table.insertRow(r)
                self.summary_table.setItem(r, 0, QTableWidgetItem(row['dept_name'] or ''))
                self._center(self.summary_table, r, 1, str(row['product_count']))
                avg = row['avg_gp'] or 0
                avg_item = NumItem(f"{avg:.1f}%")
                avg_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                avg_item.setForeground(
                    QColor("green") if avg >= 30 else QColor("orange") if avg >= 15 else QColor("red")
                )
                self.summary_table.setItem(r, 2, avg_item)
                self._center(self.summary_table, r, 3, str(row['healthy']))
                self._center(self.summary_table, r, 4, str(row['marginal']))
                self._center(self.summary_table, r, 5, str(row['low_gp']))
            self.summary_table.setSortingEnabled(True)
            self.status_label.setText(f"{len(rows)} departments")
        else:
            self.summary_table.hide()
            self.detail_table.show()
            rows = report_ctrl.get_gp_data(dept_id, gp_filter)
            self.detail_table.setSortingEnabled(False)
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
                gp_item = NumItem(f"{gp:.1f}%")
                gp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                gp_item.setForeground(color)
                self.detail_table.setItem(r, 5, gp_item)
            self.detail_table.setSortingEnabled(True)
            self.status_label.setText(
                f"{self.detail_table.rowCount()} products — "
                f"<span style='color:green'>✓ {healthy_count} healthy</span>  "
                f"<span style='color:orange'>⚠ {marginal_count} marginal</span>  "
                f"<span style='color:red'>✕ {low_count} low</span>"
            )

    def _center(self, table, row, col, text):
        item = NumItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, col, item)

    def _right(self, table, row, col, text):
        item = NumItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, col, item)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join(os.path.expanduser("~/Downloads"), "gp_report.csv"), "CSV (*.csv)")
        if not path:
            return
        rows = report_ctrl.get_gp_data(self.dept_filter.currentData(), self.gp_filter.currentData())
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Barcode", "Description", "Department", "Sell Price", "Cost Price", "GP %"])
            for row in rows:
                w.writerow([f'="{row["barcode"]}"', row['description'], row['dept_name'],
                             row['sell_price'], row['cost_price'], row['gp_pct']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
