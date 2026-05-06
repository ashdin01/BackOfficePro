import csv
import os
from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QTabWidget, QDialog, QDialogButtonBox, QFormLayout,
    QMessageBox, QFileDialog, QAbstractItemView, QFrame
)
from PyQt6.QtCore import Qt, QSortFilterProxyModel, QTimer
from PyQt6.QtGui import QColor, QFont

import controllers.product_controller as product_ctrl
from utils.error_dialog import show_error

_RED    = "#f85149"
_ORANGE = "#FF9800"
_GREEN  = "#4CAF50"
_DIM    = "#8b949e"
_BLUE   = "#5c9de8"


def _item(text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
          color=None, bold=False):
    i = QTableWidgetItem(str(text) if text is not None else "")
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        i.setForeground(QColor(color))
    if bold:
        f = i.font(); f.setBold(True); i.setFont(f)
    return i


RIGHT  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
LEFT   = Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter


class _PLUDialog(QDialog):
    """Small dialog to enter / change a PLU value."""
    def __init__(self, current_plu, description, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit PLU")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)

        desc_lbl = QLabel(description)
        desc_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        form = QFormLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Leave blank to clear")
        self._input.setText(str(current_plu) if current_plu else "")
        self._input.selectAll()
        form.addRow("PLU:", self._input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        return self._input.text().strip()


class PLUManager(QWidget):
    def __init__(self):
        super().__init__()
        self._all_rows   = []
        self._dup_rows   = []
        self._conf_rows  = []
        self._open_wins  = []
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Title + toolbar ───────────────────────────────────────────
        top = QHBoxLayout()
        title = QLabel("PLU Manager")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        top.addWidget(title)
        top.addStretch()

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setFixedHeight(30)
        self._export_btn.clicked.connect(self._export)
        top.addWidget(self._export_btn)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedHeight(30)
        refresh_btn.clicked.connect(self._refresh)
        top.addWidget(refresh_btn)
        root.addLayout(top)

        # ── Search bar ────────────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("PLU, barcode or description…")
        self._search.setMinimumHeight(30)
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search)

        self._edit_btn = QPushButton("✏  Edit PLU")
        self._edit_btn.setFixedHeight(30)
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._edit_plu)
        search_row.addWidget(self._edit_btn)

        self._clear_btn = QPushButton("✕  Clear PLU")
        self._clear_btn.setFixedHeight(30)
        self._clear_btn.setEnabled(False)
        self._clear_btn.setStyleSheet(
            "QPushButton{color:#f85149;}"
            "QPushButton:disabled{color:#444;}"
        )
        self._clear_btn.clicked.connect(self._clear_plu)
        search_row.addWidget(self._clear_btn)
        root.addLayout(search_row)

        # ── Tabs ──────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_change)

        # Tab 0 — All PLUs
        self._all_table = self._make_table()
        self._all_table.itemSelectionChanged.connect(
            lambda: self._on_selection(self._all_table))
        self._tabs.addTab(self._all_table, "All PLUs")

        # Tab 1 — Duplicates
        self._dup_table = self._make_table()
        self._dup_table.itemSelectionChanged.connect(
            lambda: self._on_selection(self._dup_table))
        self._tabs.addTab(self._dup_table, "Duplicates")

        # Tab 2 — Map Conflicts
        conf_widget = QWidget()
        conf_layout = QVBoxLayout(conf_widget)
        conf_layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            "These barcodes have a different PLU in the sales/import map vs the products table. "
            "Double-click a row to open the product and edit its PLU directly."
        )
        note.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        note.setWordWrap(True)
        conf_layout.addWidget(note)
        self._conf_table = QTableWidget()
        self._conf_table.setColumnCount(4)
        self._conf_table.setHorizontalHeaderLabels(
            ["Barcode", "Description", "PLU (Products)", "PLU (Sales/Map)"]
        )
        _hdr = self._conf_table.horizontalHeader()
        _hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c, w in [(0, 150), (2, 130), (3, 130)]:
            _hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            self._conf_table.setColumnWidth(c, w)
        self._conf_table.verticalHeader().setVisible(False)
        self._conf_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._conf_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._conf_table.setAlternatingRowColors(True)
        self._conf_table.doubleClicked.connect(
            lambda idx: self._open_product_from_table(self._conf_table, idx.row(), barcode_col=0)
        )
        conf_layout.addWidget(self._conf_table)
        self._tabs.addTab(conf_widget, "Map Conflicts")

        root.addWidget(self._tabs)

        # ── Status bar ────────────────────────────────────────────────
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        root.addWidget(self._status)

    def _make_table(self):
        t = QTableWidget()
        t.setColumnCount(6)
        t.setHorizontalHeaderLabels(
            ["PLU", "Barcode", "Description", "Dept", "Supplier", "Active"]
        )
        h = t.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c, w in [(0, 70), (1, 150), (3, 110), (4, 140), (5, 55)]:
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            t.setColumnWidth(c, w)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.setSortingEnabled(True)
        t.doubleClicked.connect(
            lambda idx, _t=t: self._open_product_from_table(_t, idx.row(), barcode_col=1)
        )
        return t

    # ── Data loading ──────────────────────────────────────────────────

    def _refresh(self):
        self._all_rows  = product_ctrl.get_all_plu_products()
        self._dup_rows  = product_ctrl.get_duplicate_plu_groups()
        self._conf_rows = product_ctrl.get_plu_map_conflicts()

        # Build set of duplicate PLUs for highlighting in all-table
        self._dup_plus = {r['plu'] for r in self._dup_rows}

        self._populate_all(self._all_rows)
        self._populate_dup(self._dup_rows)
        self._populate_conf(self._conf_rows)
        self._update_tab_labels()
        self._update_status()

    def _populate_all(self, rows):
        self._all_table.setSortingEnabled(False)
        self._all_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            is_dup = row['plu'] in self._dup_plus
            color  = _RED if is_dup else None
            self._all_table.setItem(r, 0, _item(row['plu'],         RIGHT, color, is_dup))
            self._all_table.setItem(r, 1, _item(row['barcode'],     LEFT,  color))
            self._all_table.setItem(r, 2, _item(row['description'], LEFT,  color))
            self._all_table.setItem(r, 3, _item(row['dept_name'] or '', LEFT))
            self._all_table.setItem(r, 4, _item(row['supplier_name'] or '', LEFT))
            self._all_table.setItem(r, 5, _item(
                "Yes" if row['active'] else "No", CENTER,
                _GREEN if row['active'] else _DIM
            ))
        self._all_table.setSortingEnabled(True)

    def _populate_dup(self, rows):
        self._dup_table.setSortingEnabled(False)
        self._dup_table.setRowCount(len(rows))
        current_plu = None
        for r, row in enumerate(rows):
            if row['plu'] != current_plu:
                current_plu = row['plu']
                color = _RED
            else:
                color = _ORANGE
            self._dup_table.setItem(r, 0, _item(row['plu'],         RIGHT, color, True))
            self._dup_table.setItem(r, 1, _item(row['barcode'],     LEFT,  color))
            self._dup_table.setItem(r, 2, _item(row['description'], LEFT,  color))
            self._dup_table.setItem(r, 3, _item(row['dept_name'] or '', LEFT))
            self._dup_table.setItem(r, 4, _item(row['supplier_name'] or '', LEFT))
            self._dup_table.setItem(r, 5, _item(
                "Yes" if row['active'] else "No", CENTER,
                _GREEN if row['active'] else _DIM
            ))
        self._dup_table.setSortingEnabled(True)

    def _populate_conf(self, rows):
        self._conf_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._conf_table.setItem(r, 0, _item(row['barcode']))
            self._conf_table.setItem(r, 1, _item(row['description']))
            self._conf_table.setItem(r, 2, _item(str(row['prod_plu']), CENTER, _GREEN))
            self._conf_table.setItem(r, 3, _item(str(row['map_plu']),  CENTER, _ORANGE))

    def _update_tab_labels(self):
        dup_count  = len({r['plu'] for r in self._dup_rows})
        conf_count = len(self._conf_rows)
        self._tabs.setTabText(0, f"All PLUs ({len(self._all_rows)})")
        self._tabs.setTabText(
            1,
            f"Duplicates ({dup_count} PLUs)" if dup_count else "Duplicates"
        )
        self._tabs.setTabText(
            2,
            f"Map Conflicts ({conf_count})" if conf_count else "Map Conflicts"
        )

    def _update_status(self):
        dup_count  = len({r['plu'] for r in self._dup_rows})
        conf_count = len(self._conf_rows)
        parts = [f"{len(self._all_rows)} products with PLU assigned"]
        if dup_count:
            parts.append(f"⚠  {dup_count} duplicate PLU group{'s' if dup_count != 1 else ''}")
        if conf_count:
            parts.append(f"⚠  {conf_count} map conflict{'s' if conf_count != 1 else ''}")
        if not dup_count and not conf_count:
            parts.append("✓  No conflicts")
        self._status.setText("  ·  ".join(parts))

    # ── Filtering ─────────────────────────────────────────────────────

    def _apply_filter(self):
        term = self._search.text().strip().lower()
        tab  = self._tabs.currentIndex()
        if tab == 0:
            rows = self._all_rows
            table = self._all_table
        elif tab == 1:
            rows = self._dup_rows
            table = self._dup_table
        else:
            return

        if not term:
            filtered = rows
        else:
            filtered = [
                r for r in rows
                if term in str(r['plu']).lower()
                or term in r['barcode'].lower()
                or term in (r['description'] or '').lower()
            ]

        if tab == 0:
            self._populate_all(filtered)
        else:
            self._populate_dup(filtered)

    def _on_tab_change(self, index):
        self._apply_filter()
        self._edit_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)

    # ── Selection ─────────────────────────────────────────────────────

    def _active_table(self):
        tab = self._tabs.currentIndex()
        if tab == 0:
            return self._all_table
        if tab == 1:
            return self._dup_table
        return None

    def _selected_barcode(self, table=None):
        t = table or self._active_table()
        if t is None:
            return None, None
        rows = t.selectedItems()
        if not rows:
            return None, None
        r = t.currentRow()
        barcode = t.item(r, 1).text() if t.item(r, 1) else None
        plu     = t.item(r, 0).text() if t.item(r, 0) else None
        return barcode, plu

    def _on_selection(self, table):
        if self._active_table() is not table:
            return
        barcode, _ = self._selected_barcode(table)
        has_sel = bool(barcode)
        self._edit_btn.setEnabled(has_sel)
        self._clear_btn.setEnabled(has_sel)

    # ── Actions ───────────────────────────────────────────────────────

    def _edit_plu(self):
        t = self._active_table()
        if t is None:
            return
        barcode, current_plu = self._selected_barcode(t)
        if not barcode:
            return
        desc = t.item(t.currentRow(), 2).text() if t.item(t.currentRow(), 2) else barcode

        dlg = _PLUDialog(current_plu, desc, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_plu = dlg.value()
        try:
            product_ctrl.set_product_plu(barcode, new_plu)
            product_ctrl.sync_plu_map(barcode, new_plu)
        except ValueError as e:
            QMessageBox.warning(self, "PLU Conflict", str(e))
            return
        except Exception as e:
            show_error(self, "Could not update PLU.", e)
            return
        self._refresh()

    def _clear_plu(self):
        t = self._active_table()
        if t is None:
            return
        barcode, current_plu = self._selected_barcode(t)
        if not barcode:
            return
        desc = t.item(t.currentRow(), 2).text() if t.item(t.currentRow(), 2) else barcode

        reply = QMessageBox.question(
            self, "Clear PLU",
            f"Remove PLU {current_plu} from:\n{desc}\n({barcode})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            product_ctrl.set_product_plu(barcode, '')
            product_ctrl.sync_plu_map(barcode, '')
        except Exception as e:
            show_error(self, "Could not clear PLU.", e)
            return
        self._refresh()

    def _open_product_from_table(self, table, row, barcode_col):
        item = table.item(row, barcode_col)
        if not item:
            return
        barcode = item.text().strip()
        if not barcode:
            return
        from views.products.product_edit import ProductEdit
        win = ProductEdit(barcode=barcode, on_save=self._refresh)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.destroyed.connect(lambda: self._open_wins.remove(win) if win in self._open_wins else None)
        win.show()
        win.raise_()
        win.activateWindow()
        self._open_wins.append(win)

    # ── Export ────────────────────────────────────────────────────────

    def _export(self):
        default = os.path.join(
            os.path.expanduser("~"),
            f"plu_export_{date.today().strftime('%Y%m%d')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PLU List", default, "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            dups   = product_ctrl.get_duplicate_plu_groups()
            dup_plus = {r['plu'] for r in dups}
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["PLU", "Barcode", "Description", "Dept", "Supplier",
                             "Active", "Duplicate"])
                for r in self._all_rows:
                    w.writerow([
                        r['plu'], f'="{r["barcode"]}"', r['description'],
                        r['dept_name'] or '', r['supplier_name'] or '',
                        "Yes" if r['active'] else "No",
                        "DUPLICATE" if r['plu'] in dup_plus else ""
                    ])
            QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
        except Exception as e:
            show_error(self, "Could not export PLU list.", e, title="Export Failed")
