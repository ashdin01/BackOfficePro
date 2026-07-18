import os
import csv
from datetime import date, timedelta
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QDateEdit,
    QFileDialog, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
import config.styles as styles
import controllers.report_controller as report_ctrl
from utils.error_dialog import show_error
from views.base_view import BaseView


class NumItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text().replace('%', '').replace(',', '')) < \
                   float(other.text().replace('%', '').replace(',', ''))
        except ValueError:
            return super().__lt__(other)


class WeightVarianceReport(BaseView):
    def __init__(self):
        super().__init__()
        self._last_rows = []
        self._build_ui()
        self._set_this_month()

    def showEvent(self, event):
        super().showEvent(event)
        self.load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("Weight Variance Report")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        note = QLabel(
            "⚠  Compares total received weight to total sold weight for the period — "
            "it does not account for weight still on hand, so short ranges will show "
            "apparent variance purely from timing. Most meaningful over a full month or longer."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {styles.CLR_ORANGE}; font-size: 11px;")
        layout.addWidget(note)

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

        for label, fn in [("This Month", self._set_this_month),
                           ("Last Month", self._set_last_month),
                           ("This FY",    self._set_this_fy)]:
            btn = QPushButton(label)
            btn.setStyleSheet(styles.STYLE_BTN_PERIOD)
            btn.clicked.connect(fn)
            filter_row.addWidget(btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(styles.STYLE_SEPARATOR)
        filter_row.addWidget(sep)

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
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:0 16px;font-weight:bold;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
        )
        apply_btn.clicked.connect(self.load)
        filter_row.addWidget(apply_btn)
        filter_row.addStretch()
        btn_export = QPushButton("⬇ Export CSV")
        btn_export.setMinimumHeight(32)
        btn_export.clicked.connect(self._export)
        filter_row.addWidget(btn_export)
        layout.addLayout(filter_row)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.card_received = self._make_card("Total Received", "0.00 kg", styles.CLR_TEXT)
        self.card_sold      = self._make_card("Total Sold", "0.00 kg", styles.CLR_TEXT)
        self.card_variance  = self._make_card("Variance", "0.00 kg", styles.CLR_TEXT)
        self.card_items     = self._make_card("Items Tracked", "0", styles.CLR_MUTED)
        for card in [self.card_received, self.card_sold, self.card_variance, self.card_items]:
            cards_row.addWidget(card[0])
        layout.addLayout(cards_row)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department",
            "Received (kg)", "Sold (kg)", "Variance (kg)", "Variance %"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 90)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.footer = QLabel("")
        self.footer.setStyleSheet(styles.STYLE_LABEL_MUTED)
        layout.addWidget(self.footer)

    def _make_card(self, title, value, color):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:{styles.CLR_BG_PANEL};border:1px solid {styles.CLR_BORDER};border-radius:6px;}}"
        )
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(12, 8, 12, 8)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(styles.STYLE_LABEL_MUTED)
        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: bold;")
        card_layout.addWidget(lbl_title)
        card_layout.addWidget(lbl_val)
        return frame, lbl_val

    def _load(self):
        d_from  = self.date_from.date().toPyDate()
        d_to    = self.date_to.date().toPyDate()
        dept_id = self.dept_filter.currentData()
        rows = report_ctrl.get_weight_variance(d_from, d_to, dept_id)

        total_received = total_sold = 0.0

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        for row in rows:
            received = float(row['received_weight'] or 0)
            sold     = float(row['sold_weight'] or 0)
            variance = received - sold
            var_pct  = (variance / received * 100) if received > 0 else 0.0

            total_received += received
            total_sold     += sold

            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(row['description'] or ''))
            self.table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))

            recv_item = NumItem(f"{received:.2f}")
            recv_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 3, recv_item)

            sold_item = NumItem(f"{sold:.2f}")
            sold_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 4, sold_item)

            var_item = NumItem(f"{variance:.2f}")
            var_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            var_item.setForeground(QColor(styles.CLR_DANGER) if variance > 0 else QColor(styles.CLR_SUCCESS_ALT))
            self.table.setItem(r, 5, var_item)

            pct_item = NumItem(f"{var_pct:.1f}%")
            pct_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 6, pct_item)

        self.table.setSortingEnabled(True)

        total_variance = total_received - total_sold
        self.card_received[1].setText(f"{total_received:.2f} kg")
        self.card_sold[1].setText(f"{total_sold:.2f} kg")
        self.card_variance[1].setText(f"{total_variance:.2f} kg")
        self.card_variance[1].setStyleSheet(
            f"color: {styles.CLR_DANGER if total_variance > 0 else styles.CLR_SUCCESS_ALT}; "
            "font-size: 16px; font-weight: bold;"
        )
        self.card_items[1].setText(str(len(rows)))

        period = f"{d_from.strftime('%d/%m/%Y')} – {d_to.strftime('%d/%m/%Y')}"
        self.footer.setText(f"Period: {period}  |  {len(rows)} items")
        self._last_rows = rows

    def _set_dates(self, d_from, d_to):
        self.date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self.date_to.setDate(QDate(d_to.year, d_to.month, d_to.day))
        self.load()

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
            f"Weight_Variance_Report_{date.today().strftime('%Y%m%d')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Export Weight Variance Report", default, "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["Barcode", "Description", "Department",
                            "Received (kg)", "Sold (kg)", "Variance (kg)", "Variance %"])
                for row in self._last_rows:
                    received = float(row['received_weight'] or 0)
                    sold     = float(row['sold_weight'] or 0)
                    variance = received - sold
                    var_pct  = (variance / received * 100) if received > 0 else 0.0
                    w.writerow([row['barcode'], row['description'] or '', row['dept_name'] or '',
                                f"{received:.2f}", f"{sold:.2f}", f"{variance:.2f}", f"{var_pct:.1f}%"])
            QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
        except Exception as e:
            show_error(self, "Could not export weight variance report.", e, title="Export Failed")
