from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QFileDialog, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt, QObject, QEvent, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut, QColor
from utils.keyboard_mixin import KeyboardMixin
import models.stock_on_hand as soh_model
import models.product as product_model
import csv
import os


class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text().replace("$", "")) < float(other.text().replace("$", ""))
        except ValueError:
            return super().__lt__(other)


class _SearchEscapeFilter(QObject):
    """
    Installed on the search QLineEdit.
    Escape → clear search, call on_escape callback (returns to main nav).
    All other keys pass through normally.
    """
    def __init__(self, search_input, on_escape, parent=None):
        super().__init__(parent)
        self._search    = search_input
        self._on_escape = on_escape

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._search.clear()   # triggers _search("") → full reload
                if self._on_escape:
                    self._on_escape()
                return True            # swallow Escape
        return False


class ProductList(KeyboardMixin, QWidget):
    def __init__(self, on_escape=None):
        super().__init__()
        self._on_escape = on_escape
        self._build_ui()
        self._load()

    def showEvent(self, event):
        """Auto-focus search bar every time this screen becomes visible."""
        super().showEvent(event)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── Search row ────────────────────────────────────────────────
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by barcode, PLU, description, brand, supplier or department…")
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)
        self._search_timer.timeout.connect(lambda: self._search(self.search_input.text()))
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        self.search_input.returnPressed.connect(self._focus_table)

        # Escape key: clear search, return to main nav
        self._esc_filter = _SearchEscapeFilter(self.search_input, self._on_escape)
        self.search_input.installEventFilter(self._esc_filter)

        search_row.addWidget(self.search_input)

        # ── Show Inactive checkbox ────────────────────────────────────
        self.chk_inactive = QCheckBox("Show Inactive")
        self.chk_inactive.setToolTip(
            "Show inactive products.\n"
            "Note: inactive products with non-zero stock always appear."
        )
        self.chk_inactive.stateChanged.connect(self._on_inactive_toggled)
        search_row.addWidget(self.chk_inactive)

        btn_add = QPushButton("&Add Product")
        btn_add.clicked.connect(self._add)
        search_row.addWidget(btn_add)

        btn_export = QPushButton("⬇ Export CSV")
        btn_export.clicked.connect(self._export_csv)
        search_row.addWidget(btn_export)

        layout.addLayout(search_row)

        # ── Legend ────────────────────────────────────────────────────
        self.legend = QLabel(
            "  ⚠ Orange = inactive with stock     🟢 Green = temporary barcode (TEMP-) — update when real barcode available"
        )
        self.legend.setStyleSheet("color: #aaa; font-size: 10px; padding: 2px 0;")
        self.legend.setVisible(True)
        layout.addWidget(self.legend)

        # ── Table ─────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "PLU", "Description", "Brand", "Department", "Supplier",
            "Unit", "Sell Price", "Cost Price", "On Hand", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0,  140)
        self.table.setColumnWidth(1,   65)
        self.table.setColumnWidth(3,  100)
        self.table.setColumnWidth(4,   95)
        self.table.setColumnWidth(5,  100)
        self.table.setColumnWidth(6,   45)
        self.table.setColumnWidth(7,   80)
        self.table.setColumnWidth(8,   80)
        self.table.setColumnWidth(9,   65)
        self.table.setColumnWidth(10,  70)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setMinimumSectionSize(45)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)

        QShortcut(QKeySequence("N"), self, self._add)
        QShortcut(QKeySequence("/"), self, self._focus_search)
        self.setup_keyboard(table=self.table)

    def _focus_table(self):
        self.table.setFocus()
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _show_inactive(self):
        return self.chk_inactive.isChecked()

    def _on_inactive_toggled(self):
        self.legend.setVisible(True)
        self._reload_with_search()

    def _load(self, rows=None):
        if rows is None:
            if self._show_inactive():
                rows = product_model.get_all(active_only=False)
            else:
                rows = product_model.get_all(
                    active_only=True,
                    include_nonzero_inactive=True
                )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        inactive_with_stock = 0
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            is_active   = bool(row['active'])
            soh         = soh_model.get_by_barcode(row["barcode"])
            soh_qty     = int(soh["quantity"]) if soh else 0
            is_warning  = not is_active and soh_qty != 0
            is_temp     = str(row['barcode']).startswith('TEMP-')
            if is_warning:
                inactive_with_stock += 1
            row_color = None
            if is_temp:
                row_color = QColor('#1a2a1a')
            elif is_warning:
                row_color = QColor('#3a2800')
            elif not is_active:
                row_color = QColor('#1a1a1a')
            bc_item = QTableWidgetItem(row['barcode'])
            if is_temp:
                bc_item.setForeground(QColor('#69f0ae'))
                bc_item.setToolTip('Temporary barcode — update when real barcode is scanned')
            self.table.setItem(r, 0, bc_item)
            self.table.setItem(r, 1,  QTableWidgetItem(str(row['plu'] or '')))
            self.table.setItem(r, 2,  QTableWidgetItem(row['description']))
            self.table.setItem(r, 3,  QTableWidgetItem(row['brand'] or ''))
            self.table.setItem(r, 4,  QTableWidgetItem(row['dept_name'] or ''))
            self.table.setItem(r, 5,  QTableWidgetItem(row['supplier_name'] or ''))
            self.table.setItem(r, 6,  QTableWidgetItem(row['unit'] or ''))
            self.table.setItem(r, 7,  NumericTableWidgetItem(f"${row['sell_price']:.2f}"))
            self.table.setItem(r, 8,  NumericTableWidgetItem(f"${row['cost_price']:.2f}"))
            soh_item = NumericTableWidgetItem(str(soh_qty))
            soh_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if is_warning:
                soh_item.setForeground(QColor('#FF9800'))
            elif soh_qty >= 4:
                soh_item.setForeground(QColor('#4CAF50'))
            elif soh_qty >= 0:
                soh_item.setForeground(QColor('#FF9800'))
            else:
                soh_item.setForeground(QColor('#f44336'))
            self.table.setItem(r, 9, soh_item)
            status_text = "Active" if is_active else "INACTIVE"
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_warning:
                status_item.setForeground(QColor('#FF9800'))
            elif not is_active:
                status_item.setForeground(QColor('#666666'))
            else:
                status_item.setForeground(QColor('#4CAF50'))
            self.table.setItem(r, 10, status_item)
            if row_color:
                for col in range(self.table.columnCount()):
                    item = self.table.item(r, col)
                    if item:
                        item.setBackground(row_color)
        self.table.setSortingEnabled(True)
        active_count   = sum(1 for r in range(self.table.rowCount())
                             if self.table.item(r, 10)
                             and self.table.item(r, 10).text() == "Active")
        inactive_count = self.table.rowCount() - active_count
        status_parts = [f"{self.table.rowCount()} products"]
        if inactive_with_stock > 0:
            status_parts.append(f"⚠ {inactive_with_stock} inactive with stock")
        if self._show_inactive() and inactive_count > 0:
            status_parts.append(f"{inactive_count} inactive shown")
        self.status.setText("  ·  ".join(status_parts))

    def _search(self, term):
        if term.strip():
            rows = product_model.search(term, active_only=not self._show_inactive())
            self._load(rows)
        else:
            self._load()

    def _reload_with_search(self):
        term = self.search_input.text().strip()
        if term:
            rows = product_model.search(term, active_only=not self._show_inactive())
            self._load(rows)
        else:
            self._load()

    def _add(self):
        from views.products.product_add import ProductAdd
        self.add_win = ProductAdd(on_save=self._reload_with_search)
        self.add_win.show()

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        barcode = self.table.item(row, 0).text()
        from views.products.product_edit import ProductEdit
        self.edit_win = ProductEdit(barcode=barcode, on_save=self._reload_with_search)
        self.edit_win.show()

    def _export_csv(self):
        row_count = self.table.rowCount()
        if row_count == 0:
            QMessageBox.information(self, "Export", "No products to export.")
            return
        default_path = os.path.join(os.path.expanduser("~"), "products_export.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Products to CSV", default_path,
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        col_count = self.table.columnCount()
        headers = [
            self.table.horizontalHeaderItem(c).text()
            for c in range(col_count)
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for r in range(row_count):
                    writer.writerow([
                        self.table.item(r, c).text() if self.table.item(r, c) else ""
                        for c in range(col_count)
                    ])
            QMessageBox.information(self, "Export Complete",
                f"Exported {row_count} products to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))
