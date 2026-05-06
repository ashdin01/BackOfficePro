import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QLineEdit, QDateEdit, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QDate
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


class MovementHistoryReport(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Barcode or description...")
        self.search.setMaximumWidth(200)
        filter_row.addWidget(self.search)

        filter_row.addWidget(QLabel("Type:"))
        self.type_filter = QComboBox()
        self.type_filter.addItems([
            "ALL", "RECEIPT", "SALE", "ADJUSTMENT_IN",
            "ADJUSTMENT_OUT", "WASTAGE", "SHRINKAGE", "RETURN", "STOCKTAKE"
        ])
        filter_row.addWidget(self.type_filter)

        filter_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_from.setCalendarPopup(True)
        filter_row.addWidget(self.date_from)

        filter_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        filter_row.addWidget(self.date_to)

        btn_search = QPushButton("Search")
        btn_search.clicked.connect(self._load)
        filter_row.addWidget(btn_search)

        filter_row.addStretch()
        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)
        layout.addLayout(filter_row)

        self.table = QTableWidget()
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Date/Time", "Barcode", "Description", "Type", "Qty", "Reference", "Notes"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 1, 3, 4, 5]:
            hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 110)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.doubleClicked.connect(self._open_product)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def _load(self):
        rows = report_ctrl.get_stock_movements(
            barcode=self.search.text().strip() or None,
            move_type=self.type_filter.currentText(),
            date_from=self.date_from.date().toString("yyyy-MM-dd"),
            date_to=self.date_to.date().toString("yyyy-MM-dd"),
        )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)

            self.table.setItem(r, 0, QTableWidgetItem(str(row['created_at'])[:16]))
            self.table.setItem(r, 1, QTableWidgetItem(row['barcode']))
            self.table.setItem(r, 2, QTableWidgetItem(row['description'] or ''))

            type_item = QTableWidgetItem(row['movement_type'])
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if row['movement_type'] in ('RECEIPT', 'ADJUSTMENT_IN', 'RETURN'):
                type_item.setForeground(QColor("green"))
            elif row['movement_type'] in ('SALE', 'WASTAGE', 'ADJUSTMENT_OUT', 'SHRINKAGE'):
                type_item.setForeground(QColor("red"))
            else:
                type_item.setForeground(QColor("steelblue"))
            self.table.setItem(r, 3, type_item)

            qty = row['quantity']
            qty_item = NumItem(f"{'+' if qty > 0 else ''}{qty:.0f}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_item.setForeground(QColor("green") if qty > 0 else QColor("red"))
            self.table.setItem(r, 4, qty_item)

            self.table.setItem(r, 5, QTableWidgetItem(row['reference'] or ''))
            self.table.setItem(r, 6, QTableWidgetItem(row['notes'] or ''))

        self.table.setSortingEnabled(True)
        self.status_label.setText(f"{self.table.rowCount()} movements  ·  double-click a row to view product")

    def _open_product(self, index):
        row = index.row()
        barcode_item = self.table.item(row, 1)
        if not barcode_item:
            return
        barcode = barcode_item.text()
        from views.products.product_edit import ProductEdit
        self._prod_win = ProductEdit(barcode=barcode)
        self._prod_win.show()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join(os.path.expanduser("~/Downloads"), "movements.csv"), "CSV (*.csv)")
        if not path:
            return
        rows = report_ctrl.get_stock_movements(
            barcode=self.search.text().strip() or None,
            move_type=self.type_filter.currentText(),
            date_from=self.date_from.date().toString("yyyy-MM-dd"),
            date_to=self.date_to.date().toString("yyyy-MM-dd"),
            limit=999999
        )
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Date/Time", "Barcode", "Description", "Type", "Qty", "Reference", "Notes"])
            for row in rows:
                w.writerow([row['created_at'], f'="{row["barcode"]}"', row['description'],
                             row['movement_type'], row['quantity'], row['reference'], row['notes']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
