import csv
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDateEdit, QFileDialog, QCheckBox
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QFont

import controllers.report_controller as report_ctrl

_HEADER_BG  = "#1e3a5f"
_HEADER_FG  = "#90caf9"
_TOTAL_BG   = "#162030"
_TOTAL_FG   = "#e6edf3"
_GREEN      = "#4CAF50"
_ORANGE     = "#FF9800"
_RED        = "#f44336"
_DIM        = "#8b949e"


class LiquorReport(QWidget):
    def __init__(self):
        super().__init__()
        self._data = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Liquor Tracking Report")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #e6edf3;")
        layout.addWidget(title)

        # ── Controls ──────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel("Department:"))
        self._dept_cb = QComboBox()
        self._dept_cb.setFixedWidth(200)
        self._dept_cb.setFixedHeight(30)
        self._populate_depts()
        ctrl.addWidget(self._dept_cb)

        ctrl.addSpacing(12)
        ctrl.addWidget(QLabel("From:"))
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._start_date.setDisplayFormat("dd/MM/yyyy")
        self._start_date.setFixedHeight(30)
        today = QDate.currentDate()
        self._start_date.setDate(QDate(today.year(), today.month(), 1))
        ctrl.addWidget(self._start_date)

        ctrl.addWidget(QLabel("To:"))
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        self._end_date.setDisplayFormat("dd/MM/yyyy")
        self._end_date.setFixedHeight(30)
        self._end_date.setDate(today)
        ctrl.addWidget(self._end_date)

        ctrl.addSpacing(12)
        self._movement_only_cb = QCheckBox("Movement only")
        self._movement_only_cb.setToolTip("Hide products with no transactions in the period")
        ctrl.addWidget(self._movement_only_cb)

        ctrl.addSpacing(12)
        run_btn = QPushButton("▶  Run Report")
        run_btn.setFixedHeight(32)
        run_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;border-radius:4px;"
            "padding:0 16px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        run_btn.clicked.connect(self._run)
        ctrl.addWidget(run_btn)

        ctrl.addStretch()

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setFixedHeight(32)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_csv)
        ctrl.addWidget(self._export_btn)

        layout.addLayout(ctrl)

        # ── Table ─────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["Description", "Unit", "SOH Start", "IN  ↑", "OUT  ↓", "SOH End"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in [(1, 55), (2, 95), (3, 85), (4, 85), (5, 95)]:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self._table.setColumnWidth(col, w)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #1e2a38; alternate-background-color: #1b2738;
                gridline-color: #2a3a4a; font-size: 13px; border: none;
            }
            QHeaderView::section {
                background: #152030; color: #8b949e;
                font-size: 12px; font-weight: bold; padding: 6px;
                border: none; border-bottom: 1px solid #2a3a4a;
            }
            QTableWidget::item:selected { background: #1e4080; color: #e6edf3; }
        """)
        layout.addWidget(self._table, stretch=1)

        # ── Status bar ────────────────────────────────────────────────
        self._status_lbl = QLabel("Select a date range and click Run Report.")
        self._status_lbl.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        layout.addWidget(self._status_lbl)

    def _populate_depts(self):
        self._dept_cb.addItem("— All Departments —", None)
        for r in report_ctrl.get_all_departments():
            self._dept_cb.addItem(f"{r['code']}  —  {r['name']}", r['id'])
            if r['code'] == 'LIQ':
                self._dept_cb.setCurrentIndex(self._dept_cb.count() - 1)

    # ── Query ─────────────────────────────────────────────────────────

    def _run(self):
        dept_id = self._dept_cb.currentData()
        start   = self._start_date.date().toString("yyyy-MM-dd")
        end     = self._end_date.date().toString("yyyy-MM-dd")
        if start > end:
            self._status_lbl.setText("Start date must be before end date.")
            return

        rows = report_ctrl.get_liquor_tracking(
            dept_id=dept_id, date_from=start, date_to=end
        )
        movement_only = self._movement_only_cb.isChecked()
        self._populate_table(rows, start, end, movement_only)

    # ── Render ────────────────────────────────────────────────────────

    def _populate_table(self, rows, start, end, movement_only):
        self._table.setRowCount(0)
        self._data = []

        current_group = None
        group_in = group_out = group_start = group_end = 0.0
        grand_in = grand_out = grand_start = grand_end = 0.0
        product_count = 0

        def flush_group_total():
            nonlocal current_group
            if current_group is None:
                return
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setRowHeight(r, 26)
            self._table.setSpan(r, 0, 1, 2)
            lbl = self._mk_item(f"  {current_group}  total", bold=True, bg=_TOTAL_BG, fg=_TOTAL_FG)
            lbl.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(r, 0, lbl)
            self._table.setItem(r, 2, self._num_item(group_start, bold=True, bg=_TOTAL_BG))
            self._table.setItem(r, 3, self._num_item(group_in,    bold=True, bg=_TOTAL_BG, color=_GREEN if group_in else None))
            self._table.setItem(r, 4, self._num_item(group_out,   bold=True, bg=_TOTAL_BG, color=_ORANGE if group_out else None))
            self._table.setItem(r, 5, self._num_item(group_end,   bold=True, bg=_TOTAL_BG, color=_RED if group_end < 0 else None))

        for row in rows:
            soh_end   = round(float(row['current_soh']) - float(row['after_end_net']), 3)
            soh_start = round(soh_end - float(row['period_net']), 3)
            p_in      = round(float(row['period_in']),  3)
            p_out     = round(float(row['period_out']), 3)

            if movement_only and p_in == 0 and p_out == 0:
                continue

            group = row['group_name']

            if group != current_group:
                flush_group_total()
                self._add_group_header(group)
                current_group = group
                group_in = group_out = group_start = group_end = 0.0

            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setRowHeight(r, 28)

            desc = QTableWidgetItem(row['description'])
            desc.setToolTip(row['barcode'])
            self._table.setItem(r, 0, desc)

            self._table.setItem(r, 1, self._mk_item(row['unit'], align=Qt.AlignmentFlag.AlignCenter))
            self._table.setItem(r, 2, self._num_item(soh_start))
            self._table.setItem(r, 3, self._num_item(p_in,  color=_GREEN  if p_in  else _DIM))
            self._table.setItem(r, 4, self._num_item(p_out, color=_ORANGE if p_out else _DIM))
            self._table.setItem(r, 5, self._num_item(soh_end, color=_RED if soh_end < 0 else None))

            group_start += soh_start; group_end += soh_end
            group_in    += p_in;      group_out += p_out
            grand_start += soh_start; grand_end += soh_end
            grand_in    += p_in;      grand_out += p_out
            product_count += 1

            self._data.append({
                'Group': group, 'Description': row['description'],
                'Unit': row['unit'], 'SOH Start': soh_start,
                'IN': p_in, 'OUT': p_out, 'SOH End': soh_end,
            })

        flush_group_total()

        # Grand total row
        if product_count:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setRowHeight(r, 30)
            self._table.setSpan(r, 0, 1, 2)
            lbl = self._mk_item("  GRAND TOTAL", bold=True, bg="#0d1a24", fg="#e6edf3")
            lbl.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(r, 0, lbl)
            self._table.setItem(r, 2, self._num_item(grand_start, bold=True, bg="#0d1a24"))
            self._table.setItem(r, 3, self._num_item(grand_in,    bold=True, bg="#0d1a24", color=_GREEN  if grand_in  else None))
            self._table.setItem(r, 4, self._num_item(grand_out,   bold=True, bg="#0d1a24", color=_ORANGE if grand_out else None))
            self._table.setItem(r, 5, self._num_item(grand_end,   bold=True, bg="#0d1a24", color=_RED    if grand_end < 0 else None))

        self._export_btn.setEnabled(bool(self._data))
        self._status_lbl.setText(
            f"{product_count} product{'s' if product_count != 1 else ''}  ·  "
            f"{start} → {end}  ·  "
            f"Net movement: {self._fmt(grand_in - grand_out)}"
        )

    def _add_group_header(self, name):
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setRowHeight(r, 32)
        self._table.setSpan(r, 0, 1, 6)
        item = self._mk_item(f"  {name.upper()}", bold=True, bg=_HEADER_BG, fg=_HEADER_FG)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._table.setItem(r, 0, item)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _mk_item(text, bold=False, bg=None, fg=None, align=None):
        item = QTableWidgetItem(str(text))
        if bold:
            f = item.font(); f.setBold(True); item.setFont(f)
        if bg:
            item.setBackground(QColor(bg))
        if fg:
            item.setForeground(QColor(fg))
        if align:
            item.setTextAlignment(align)
        return item

    def _num_item(self, val, bold=False, bg=None, color=None):
        item = self._mk_item(self._fmt(val) if val != 0 else "—", bold=bold, bg=bg)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if color:
            item.setForeground(QColor(color))
        elif val == 0:
            item.setForeground(QColor(_DIM))
        return item

    @staticmethod
    def _fmt(val):
        if val == 0:
            return "0"
        if val == int(val):
            return str(int(val))
        return f"{val:.3f}".rstrip('0').rstrip('.')

    # ── Export ────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._data:
            return
        default = os.path.join(
            os.path.expanduser("~"),
            f"liquor_report_{datetime.now().strftime('%Y%m%d')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", default, "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['Group', 'Description', 'Unit', 'SOH Start', 'IN', 'OUT', 'SOH End'])
            writer.writeheader()
            writer.writerows(self._data)
