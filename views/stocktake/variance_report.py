from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QColor
import models.stocktake as stocktake_model
import csv
import os


class VarianceReport(QWidget):
    def __init__(self, session_id, session_label, on_apply=None):
        super().__init__()
        self.session_id = session_id
        self.session_label = session_label
        self.on_apply = on_apply
        self.setWindowTitle(f"Variance Report — {session_label}")
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        hdr = QHBoxLayout()
        self.title = QLabel(f"<b>Variance Report: {self.session_label}</b>")
        hdr.addWidget(self.title)
        hdr.addStretch()

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "Show All",
            "Variances Only",
            "Shortages Only (negative)",
            "Surpluses Only (positive)",
            "Not Counted",
        ])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        hdr.addWidget(QLabel("Filter:"))
        hdr.addWidget(self.filter_combo)
        layout.addLayout(hdr)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department",
            "SOH Qty", "Counted Qty", "Variance (Units)",
            "Cost Price", "Variance ($)", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # Summary bar
        self.summary = QLabel("")
        self.summary.setStyleSheet("padding: 6px; font-size: 12px;")
        layout.addWidget(self.summary)

        # Buttons
        btns = QHBoxLayout()

        btn_export = QPushButton("⬇ Export CSV")
        btn_export.setFixedHeight(34)
        btn_export.clicked.connect(self._export_csv)

        btn_apply = QPushButton("✓ Apply Stocktake && Close Session")
        btn_apply.setFixedHeight(34)
        btn_apply.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")
        btn_apply.clicked.connect(self._apply_session)

        btn_close = QPushButton("Close  [Esc]")
        btn_close.setFixedHeight(34)
        btn_close.clicked.connect(self.close)

        btns.addWidget(btn_export)
        btns.addStretch()
        btns.addWidget(btn_apply)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        self._rows = stocktake_model.get_variance_report(self.session_id)
        self._apply_filter()

    def _apply_filter(self):
        f = self.filter_combo.currentText()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        total_lines     = 0
        counted_lines   = 0
        not_counted     = 0
        variance_units  = 0.0
        variance_cost   = 0.0
        shrinkage_cost  = 0.0

        for c in self._rows:
            soh     = float(c['soh_qty'])
            counted = float(c['counted_qty']) if c['counted_qty'] is not None else None
            variance = (counted - soh) if counted is not None else None
            cost    = float(c['cost_price'] or 0)
            var_val = (variance * cost) if variance is not None else None

            total_lines += 1
            if counted is None:
                not_counted += 1
                status = "NOT COUNTED"
            elif variance == 0:
                counted_lines += 1
                status = "OK"
            elif variance > 0:
                counted_lines += 1
                status = "SURPLUS"
                variance_units += variance
                variance_cost  += var_val
            else:
                counted_lines += 1
                status = "SHORTAGE"
                variance_units += variance
                variance_cost  += var_val
                shrinkage_cost += var_val

            # Apply filter
            if f == "Variances Only"          and (variance is None or variance == 0): continue
            if f == "Shortages Only (negative)" and (variance is None or variance >= 0): continue
            if f == "Surpluses Only (positive)" and (variance is None or variance <= 0): continue
            if f == "Not Counted"              and status != "NOT COUNTED": continue

            r = self.table.rowCount()
            self.table.insertRow(r)

            self.table.setItem(r, 0, QTableWidgetItem(c['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(c['description']))
            self.table.setItem(r, 2, QTableWidgetItem(c['dept_name'] or ''))

            soh_item = QTableWidgetItem(f"{soh:.0f}")
            soh_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, soh_item)

            if counted is not None:
                cnt_item = QTableWidgetItem(f"{counted:.0f}")
            else:
                cnt_item = QTableWidgetItem("—")
                cnt_item.setForeground(QColor("#888888"))
            cnt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, cnt_item)

            if variance is not None:
                var_item = QTableWidgetItem(f"{variance:+.0f}")
                var_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if variance > 0:
                    var_item.setForeground(QColor("#4caf50"))
                elif variance < 0:
                    var_item.setForeground(QColor("#f44336"))
            else:
                var_item = QTableWidgetItem("—")
                var_item.setForeground(QColor("#888888"))
                var_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 5, var_item)

            cost_item = QTableWidgetItem(f"${cost:.2f}")
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 6, cost_item)

            if var_val is not None:
                vv_item = QTableWidgetItem(f"${var_val:+.2f}")
                vv_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if var_val < 0:
                    vv_item.setForeground(QColor("#f44336"))
                elif var_val > 0:
                    vv_item.setForeground(QColor("#4caf50"))
            else:
                vv_item = QTableWidgetItem("—")
                vv_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                vv_item.setForeground(QColor("#888888"))
            self.table.setItem(r, 7, vv_item)

            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "SHORTAGE":
                status_item.setForeground(QColor("#f44336"))
            elif status == "SURPLUS":
                status_item.setForeground(QColor("#4caf50"))
            elif status == "NOT COUNTED":
                status_item.setForeground(QColor("#888888"))
            self.table.setItem(r, 8, status_item)

        self.table.setSortingEnabled(True)

        sign = "+" if variance_cost >= 0 else ""
        self.summary.setText(
            f"Total Products: {total_lines}  |  "
            f"Counted: {counted_lines}  |  "
            f"Not Counted: {not_counted}  |  "
            f"Variance Units: {variance_units:+.0f}  |  "
            f"Variance Value: {sign}${variance_cost:.2f}  |  "
            f"<b style='color:#f44336'>Shrinkage: ${shrinkage_cost:.2f}</b>"
        )
        self.summary.setTextFormat(Qt.TextFormat.RichText)

    def _export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Export", "No rows to export.")
            return
        default = os.path.join(
            os.path.expanduser("~"),
            f"variance_{self.session_label.replace(' ', '_')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Variance Report", default,
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        cols = self.table.columnCount()
        headers = [self.table.horizontalHeaderItem(c).text() for c in range(cols)]
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for r in range(self.table.rowCount()):
                    writer.writerow([
                        self.table.item(r, c).text() if self.table.item(r, c) else ""
                        for c in range(cols)
                    ])
            QMessageBox.information(self, "Exported",
                f"Exported {self.table.rowCount()} rows to:
{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _apply_session(self):
        counted = sum(
            1 for c in self._rows if c['counted_qty'] is not None
        )
        not_cnt = sum(
            1 for c in self._rows if c['counted_qty'] is None
        )
        msg = (
            f"Apply stocktake to stock on hand?

"
            f"  Counted products:     {counted}
"
            f"  Not counted products: {not_cnt}

"
            "Products not counted will keep their current SOH.
"
            "This cannot be undone."
        )
        reply = QMessageBox.question(
            self, "Confirm Apply", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                stocktake_model.apply_session(self.session_id)
                QMessageBox.information(
                    self, "Complete",
                    f"Stocktake applied. {counted} product(s) updated."
                )
                if self.on_apply:
                    self.on_apply()
                self.close()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
