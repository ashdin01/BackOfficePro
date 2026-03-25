from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QDoubleSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
import models.stock_on_hand as soh_model
from database.connection import get_connection


def _btn(text, color=None):
    b = QPushButton(text)
    b.setFixedHeight(35)
    if color:
        b.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold;")
    return b


def _make_table(headers, stretch_col=1):
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    return t


def _item(text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
    i = QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    return i


CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter


def search_products(term):
    """Delegate to product_model.search() for consistent multi-word PLU/barcode/description search."""
    import models.product as product_model
    return product_model.search(term, active_only=True)


class StockAdjustView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Stock Adjust")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Manually adjust stock on hand for any product"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by barcode, PLU, description, brand, supplier or department…")
        self.search.setMinimumHeight(36)
        self.search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search)

        self.results_table = _make_table(
            ["Barcode", "Description", "Supplier SKU", "Department", "On Hand", "Select"],
            stretch_col=1
        )
        self.results_table.setColumnWidth(0, 140)
        self.results_table.setColumnWidth(2, 120)
        self.results_table.setColumnWidth(3, 110)
        self.results_table.setColumnWidth(4, 80)
        self.results_table.setColumnWidth(5, 80)
        self.results_table.setMaximumHeight(260)
        layout.addWidget(self.results_table)

        self.selected_label = QLabel("No product selected")
        self.selected_label.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: steelblue; "
            "padding: 8px; background: #1e2a38; border-radius: 4px;"
        )
        layout.addWidget(self.selected_label)

        ctrl_row = QHBoxLayout()

        type_col = QVBoxLayout()
        type_col.addWidget(QLabel("Adjustment Type"))
        self.adj_type = QComboBox()
        self.adj_type.addItems([
            "ADJUSTMENT", "RECEIPT", "TRANSFER IN",
            "TRANSFER OUT", "WASTAGE", "CORRECTION"
        ])
        self.adj_type.setMinimumHeight(36)
        type_col.addWidget(self.adj_type)
        ctrl_row.addLayout(type_col)

        qty_col = QVBoxLayout()
        qty_col.addWidget(QLabel("Quantity  (negative = reduce)"))
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(-999999, 999999)
        self.qty_spin.setDecimals(2)
        self.qty_spin.setValue(0)
        self.qty_spin.setMinimumHeight(36)
        qty_col.addWidget(self.qty_spin)
        ctrl_row.addLayout(qty_col)

        ref_col = QVBoxLayout()
        ref_col.addWidget(QLabel("Reference (optional)"))
        self.ref_input = QLineEdit()
        self.ref_input.setPlaceholderText("e.g. Invoice #1234")
        self.ref_input.setMinimumHeight(36)
        ref_col.addWidget(self.ref_input)
        ctrl_row.addLayout(ref_col)

        notes_col = QVBoxLayout()
        notes_col.addWidget(QLabel("Notes (optional)"))
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Reason for adjustment…")
        self.notes_input.setMinimumHeight(36)
        notes_col.addWidget(self.notes_input)
        ctrl_row.addLayout(notes_col)

        layout.addLayout(ctrl_row)

        btn_row = QHBoxLayout()
        self.apply_btn = _btn("✓  Apply Adjustment", "#2e7d32")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        self.clear_btn = _btn("Clear")
        self.clear_btn.clicked.connect(self._clear_selection)
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("<b>Recent Adjustments</b>"))
        self.history_table = _make_table(
            ["Date", "Barcode", "Description", "Type", "Qty", "Reference", "Notes"],
            stretch_col=2
        )
        self.history_table.setColumnWidth(0, 140)
        self.history_table.setColumnWidth(1, 130)
        self.history_table.setColumnWidth(3, 110)
        self.history_table.setColumnWidth(4, 70)
        self.history_table.setColumnWidth(5, 120)
        layout.addWidget(self.history_table)

        self._selected_barcode = None
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_search)
        self._load_history()

    def _on_search_changed(self):
        self._timer.start(250)

    def _do_search(self):
        query = self.search.text().strip()
        self.results_table.setRowCount(0)
        if len(query) < 2:
            return
        products = search_products(query)
        for p in products:
            soh = soh_model.get_by_barcode(p["barcode"])
            on_hand = int(soh["quantity"]) if soh else 0
            r = self.results_table.rowCount()
            self.results_table.insertRow(r)
            self.results_table.setItem(r, 0, _item(p["barcode"]))
            self.results_table.setItem(r, 1, _item(p["description"]))
            self.results_table.setItem(r, 2, _item(p["supplier_sku"] or ""))
            self.results_table.setItem(r, 3, _item(p["department_name"] or ""))
            self.results_table.setItem(r, 4, _item(str(on_hand), CENTER))
            sel_btn = QPushButton("Select")
            sel_btn.setFixedHeight(26)
            sel_btn.clicked.connect(
                lambda _, bc=p["barcode"], nm=p["description"]: self._select(bc, nm)
            )
            self.results_table.setCellWidget(r, 5, sel_btn)

    def _select(self, barcode, description):
        self._selected_barcode = barcode
        soh = soh_model.get_by_barcode(barcode)
        on_hand = int(soh["quantity"]) if soh else 0
        self.selected_label.setText(
            f"Selected: {description}   |   Barcode: {barcode}   |   Current Stock: {on_hand}"
        )
        self.apply_btn.setEnabled(True)
        self.qty_spin.setFocus()

    def _apply(self):
        if not self._selected_barcode:
            return
        qty = self.qty_spin.value()
        if qty == 0:
            QMessageBox.warning(self, "Invalid", "Quantity cannot be zero.")
            return
        try:
            soh_model.adjust(
                self._selected_barcode, qty,
                self.adj_type.currentText(),
                reference=self.ref_input.text().strip() or None,
                notes=self.notes_input.text().strip() or None,
            )
            soh = soh_model.get_by_barcode(self._selected_barcode)
            new_qty = int(soh["quantity"]) if soh else 0
            QMessageBox.information(self, "Done",
                f"Adjustment applied.\nNew stock on hand: {new_qty}")
            self._clear_selection()
            self._load_history()
            self._do_search()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _clear_selection(self):
        self._selected_barcode = None
        self.selected_label.setText("No product selected")
        self.apply_btn.setEnabled(False)
        self.qty_spin.setValue(0)
        self.ref_input.clear()
        self.notes_input.clear()

    def _load_history(self):
        conn = get_connection()
        rows = conn.execute("""
            SELECT m.created_at, m.barcode, p.description,
                   m.movement_type, m.quantity, m.reference, m.notes
            FROM stock_movements m
            LEFT JOIN products p ON m.barcode = p.barcode
            WHERE m.movement_type NOT IN ('SALE', 'RECEIPT')
            ORDER BY m.created_at DESC LIMIT 100
        """).fetchall()
        conn.close()
        self.history_table.setRowCount(0)
        for row in rows:
            r = self.history_table.rowCount()
            self.history_table.insertRow(r)
            self.history_table.setItem(r, 0, _item((row[0] or "")[:16]))
            self.history_table.setItem(r, 1, _item(row[1] or ""))
            self.history_table.setItem(r, 2, _item(row[2] or ""))
            self.history_table.setItem(r, 3, _item(row[3] or ""))
            qty = row[4] or 0
            qi = _item(f"{qty:+.0f}", CENTER)
            qi.setForeground(QColor("#4caf50" if qty > 0 else "#f44336"))
            self.history_table.setItem(r, 4, qi)
            self.history_table.setItem(r, 5, _item(row[5] or ""))
            self.history_table.setItem(r, 6, _item(row[6] or ""))
