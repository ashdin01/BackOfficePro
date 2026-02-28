from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QLineEdit, QDateEdit, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from database.connection import get_connection
import csv


def get_movements(barcode=None, move_type=None, date_from=None, date_to=None, limit=500):
    conn = get_connection()
    sql = """
        SELECT sm.id, sm.barcode, p.description, sm.movement_type,
               sm.quantity, sm.reference, sm.created_at
        FROM stock_movements sm
        LEFT JOIN products p ON sm.barcode = p.barcode
        WHERE 1=1
    """
    params = []
    if barcode:
        sql += " AND sm.barcode LIKE ?"
        params.append(f"%{barcode}%")
    if move_type and move_type != "ALL":
        sql += " AND sm.movement_type = ?"
        params.append(move_type)
    if date_from:
        sql += " AND date(sm.created_at) >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date(sm.created_at) <= ?"
        params.append(date_to)
    sql += f" ORDER BY sm.created_at DESC LIMIT {limit}"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


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
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Date/Time", "Barcode", "Description", "Type", "Qty", "Reference"
        ])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def _load(self):
        rows = get_movements(
            barcode=self.search.text().strip() or None,
            move_type=self.type_filter.currentText(),
            date_from=self.date_from.date().toString("yyyy-MM-dd"),
            date_to=self.date_to.date().toString("yyyy-MM-dd"),
        )
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
            qty_item = QTableWidgetItem(f"{'+' if qty > 0 else ''}{qty:.0f}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_item.setForeground(QColor("green") if qty > 0 else QColor("red"))
            self.table.setItem(r, 4, qty_item)

            self.table.setItem(r, 5, QTableWidgetItem(row['reference'] or ''))

        self.status_label.setText(f"{self.table.rowCount()} movements shown  (max 500)")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "movements.csv", "CSV (*.csv)")
        if not path:
            return
        rows = get_movements(
            barcode=self.search.text().strip() or None,
            move_type=self.type_filter.currentText(),
            date_from=self.date_from.date().toString("yyyy-MM-dd"),
            date_to=self.date_to.date().toString("yyyy-MM-dd"),
            limit=999999
        )
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Date/Time", "Barcode", "Description", "Type", "Qty", "Reference"])
            for row in rows:
                w.writerow([row['created_at'], row['barcode'], row['description'],
                             row['movement_type'], row['quantity'], row['reference']])
        QMessageBox.information(self, "Export", f"Exported to {path}")
