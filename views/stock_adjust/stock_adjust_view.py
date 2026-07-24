from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QDoubleSpinBox, QMessageBox, QDialog,
    QAbstractItemView, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QObject, QEvent, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
import controllers.product_controller as product_controller
import config.styles as styles
from utils.stock_events import stock_events


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
    """Delegate to product_controller.search_products() for consistent multi-word PLU/barcode/description search."""
    return product_controller.search_products(term, active_only=True)


# ── Adjustment reason codes ──────────────────────────────────────────────
REASON_CODES = [
    ("IS", "Incorrectly Sold"),
    ("NS", "Not on Shelf"),
    ("OD", "Out of Date"),
    ("IE", "Invoice Error"),
    ("SE", "Stocktake Error"),
    ("DG", "Damaged Goods"),
    ("CI", "Consumed Instore (Staff feeding/meals)"),
    ("SA", "Stock Adjust Error"),
]
REASON_MAP = {code: desc for code, desc in REASON_CODES}


class _ConfirmAdjustDialog(QDialog):
    """Confirm or cancel an adjustment."""
    def __init__(self, description, barcode, qty, reason, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Adjustment")
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setStyleSheet(f"""
            QDialog  {{ background: {styles.CLR_BG}; color: {styles.CLR_TEXT}; }}
            QLabel   {{ color: {styles.CLR_TEXT}; background: transparent; }}
            QPushButton {{ border-radius: 4px; padding: 8px 20px;
                          font-size: 13px; font-weight: bold; }}
            QFrame   {{ color: {styles.CLR_BORDER}; }}
        """)
        self._build(description, barcode, qty, reason)

    def _build(self, description, barcode, qty, reason):
        from PyQt6.QtWidgets import QFrame
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Confirm Stock Adjustment")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {styles.CLR_TEXT};")
        layout.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {styles.CLR_BORDER};"); layout.addWidget(sep)

        qty_col = styles.CLR_SUCCESS if qty > 0 else styles.CLR_DANGER
        qty_str = f"+{qty:.2f}" if qty > 0 else f"{qty:.2f}"
        details = QLabel(
            f"<table cellpadding='4'>"
            f"<tr><td>Product:</td><td><b>{description}</b></td></tr>"
            f"<tr><td>Barcode:</td><td>{barcode}</td></tr>"
            f"<tr><td>Quantity:</td><td><b style='color:{qty_col}'>{qty_str}</b></td></tr>"
            f"<tr><td>Reason:</td><td>{reason}</td></tr>"
            f"</table>"
        )
        details.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(details)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {styles.CLR_BORDER};"); layout.addWidget(sep2)

        btn_row = QHBoxLayout(); btn_row.setSpacing(10)

        self.btn_confirm = QPushButton("Confirm Adjustment  [C]")
        self.btn_confirm.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_SUCCESS_DARK};color:white;border:1px solid {styles.CLR_SUCCESS_HOVER};}}"
            f"QPushButton:hover{{background:{styles.CLR_SUCCESS_HOVER};}}"
            "QPushButton:focus{border:2px solid #66bb6a;}")
        self.btn_confirm.setDefault(False)
        self.btn_confirm.setAutoDefault(False)

        self.btn_cancel = QPushButton("Cancel  [Esc]")
        self.btn_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{styles.CLR_MUTED};border:1px solid {styles.CLR_BORDER};}}"
            f"QPushButton:hover{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};}}"
            "QPushButton:focus{border:2px solid #58a6ff;}")
        self.btn_cancel.setDefault(False)
        self.btn_cancel.setAutoDefault(False)

        self.btn_confirm.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_confirm)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        # Default focus on Confirm
        self.btn_confirm.setFocus()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_C:
            self.accept()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Fire whichever button has focus
            if self.btn_cancel.hasFocus():
                self.reject()
            else:
                self.accept()
        elif key == Qt.Key.Key_Tab:
            # Toggle focus between the two buttons
            if self.btn_confirm.hasFocus():
                self.btn_cancel.setFocus()
            else:
                self.btn_confirm.setFocus()
        else:
            super().keyPressEvent(event)


class _ReasonLookupDialog(QDialog):
    """F2 popup — select an adjustment reason code."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_code = None
        self.setWindowTitle("Adjustment Reason Codes")
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setStyleSheet(f"""
            QDialog   {{ background: {styles.CLR_BG}; color: {styles.CLR_TEXT}; }}
            QLabel    {{ color: {styles.CLR_TEXT}; background: transparent; }}
            QTableWidget {{ background: {styles.CLR_BG}; color: {styles.CLR_TEXT};
                           gridline-color: {styles.CLR_BORDER};
                           selection-background-color: {styles.CLR_ACCENT}; }}
            QTableWidget::item {{ background: {styles.CLR_BG}; color: {styles.CLR_TEXT}; }}
            QTableWidget::item:selected {{ background: {styles.CLR_ACCENT}; }}
            QHeaderView::section {{ background: {styles.CLR_BG_PANEL}; color: {styles.CLR_TEXT};
                                   border: 1px solid {styles.CLR_BORDER}; padding: 4px; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        lbl = QLabel("Select reason code  (Enter to confirm, Esc to cancel)")
        lbl.setStyleSheet(f"color: {styles.CLR_MUTED}; font-size: 11px;")
        layout.addWidget(lbl)
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Code", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(len(REASON_CODES))
        for r, (code, desc) in enumerate(REASON_CODES):
            c = QTableWidgetItem(code)
            c.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 0, c)
            self.table.setItem(r, 1, QTableWidgetItem(desc))
        self.table.selectRow(0)
        self.table.doubleClicked.connect(self._confirm)
        layout.addWidget(self.table)
        self.table.setFocus()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def _confirm(self):
        row = self.table.currentRow()
        if row >= 0:
            self.selected_code = self.table.item(row, 0).text()
            self.accept()


class _SpinEnterFilter(QObject):
    """Enter on a QDoubleSpinBox → focus next widget."""
    def __init__(self, next_widget, parent=None):
        super().__init__(parent)
        self._next = next_widget
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._next.setFocus()
                if hasattr(self._next, 'selectAll'):
                    self._next.selectAll()
                return True
        return False


class _LineEnterFilter(QObject):
    """Enter on a QLineEdit → click next widget (button)."""
    def __init__(self, next_widget, parent=None):
        super().__init__(parent)
        self._next = next_widget
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._next.setFocus()
                return True
        return False


class _SearchEnterFilter(QObject):
    """Enter in search bar → select first result row, or focus history table if no results."""
    def __init__(self, search, results_table, history_table, parent=None):
        super().__init__(parent)
        self._search  = search
        self._results = results_table
        self._history = history_table

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._results.rowCount() > 0:
                    self._results.setFocus()
                    self._results.selectRow(0)
                    return True
                elif self._history.rowCount() > 0:
                    self._history.setFocus()
                    self._history.selectRow(0)
                    return True
        return False


class _AdjustWorker(QObject):
    """Runs the DB write and history fetch on a background thread."""
    finished = pyqtSignal(int, object)  # new_qty, history_rows
    error    = pyqtSignal(str)

    def __init__(self, barcode, qty, adj_type, reference, notes):
        super().__init__()
        self._barcode   = barcode
        self._qty       = qty
        self._adj_type  = adj_type
        self._reference = reference
        self._notes     = notes

    def run(self):
        try:
            product_controller.adjust_soh(
                self._barcode, self._qty, self._adj_type,
                reference=self._reference, notes=self._notes,
            )
            soh     = product_controller.get_soh_by_barcode(self._barcode)
            new_qty = int(soh["quantity"]) if soh else 0
            rows    = product_controller.get_recent_adjustments(limit=100)
            self.finished.emit(new_qty, rows)
        except Exception as e:
            self.error.emit(str(e))


class StockAdjustView(QWidget):
    stock_changed = pyqtSignal()

    def __init__(self, current_user=None):
        super().__init__()
        self._current_user = current_user or {}
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
        self.results_table.itemActivated.connect(self._on_result_activated)
        layout.addWidget(self.results_table)

        self.selected_label = QLabel("No product selected")
        self.selected_label.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: steelblue; "
            f"padding: 8px; background: {styles.CLR_BG_PANEL}; border-radius: 4px;"
        )
        layout.addWidget(self.selected_label)

        ctrl_row = QHBoxLayout()
        qty_col = QVBoxLayout()
        qty_col.addWidget(QLabel("Quantity  (negative = reduce)"))
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(-999999, 999999)
        self.qty_spin.setDecimals(2)
        self.qty_spin.setValue(0)
        self.qty_spin.setMinimumHeight(36)
        qty_col.addWidget(self.qty_spin)
        ctrl_row.addLayout(qty_col)
        type_col = QVBoxLayout()
        type_col.addWidget(QLabel("Reason Code  (F2 to browse)"))
        type_row = QHBoxLayout()
        type_row.setSpacing(4)
        self.adj_type = QLineEdit()
        self.adj_type.setPlaceholderText("IS, NS, OD, IE, SE, DG, CI, SA …")
        self.adj_type.setMinimumHeight(36)
        self.adj_type.setMaximumWidth(120)
        self.adj_type.textChanged.connect(self._on_reason_changed)
        self.reason_desc_lbl = QLabel("")
        self.reason_desc_lbl.setStyleSheet(f"color: {styles.CLR_SUCCESS_ALT}; font-size: 11px; padding-left: 4px;")
        self.reason_desc_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        f2_btn = QPushButton("🔍")
        f2_btn.setFixedSize(36, 36)
        f2_btn.setToolTip("F2 — browse reason codes")
        f2_btn.clicked.connect(self._open_reason_lookup)
        type_row.addWidget(self.adj_type)
        type_row.addWidget(f2_btn)
        type_row.addWidget(self.reason_desc_lbl)
        type_col.addLayout(type_row)
        ctrl_row.addLayout(type_col)
        QShortcut(QKeySequence("F2"), self, self._open_reason_lookup)
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
        self.apply_btn = _btn("✓  Apply Adjustment", styles.CLR_SUCCESS_DARK)
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
        self._selected_description = None
        self._thread = None
        self._worker = None
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_search)

        # Stock can change from other processes (POS terminals, Android
        # stocktake app) while a product sits selected on this screen —
        # Qt signals can't cross that process boundary, so poll instead.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._refresh_selected_soh)

        # Same-process changes (PO receipt, credit return, stocktake apply,
        # ATRIA import) arrive instantly via the shared signal.
        stock_events.changed.connect(self._on_external_stock_change)

        # Enter in search → jump to results table (first row selected)
        self._enter_filter = _SearchEnterFilter(
            self.search, self.results_table, self.history_table)
        self.search.installEventFilter(self._enter_filter)

        # Enter in qty_spin → move focus to reason code field
        self._qty_filter = _SpinEnterFilter(self.adj_type, self)
        self.qty_spin.installEventFilter(self._qty_filter)

        # Enter in adj_type → move focus to Apply Adjustment button
        self._reason_filter = _LineEnterFilter(self.apply_btn, self)
        self.adj_type.installEventFilter(self._reason_filter)

        self._load_history()

    def showEvent(self, event):
        """Auto-focus search bar when Stock Adjust screen becomes visible."""
        super().showEvent(event)
        self.search.setFocus()
        self.search.selectAll()
        if self._selected_barcode:
            self._refresh_selected_soh()
            self._poll_timer.start()

    def hideEvent(self, event):
        """Stop polling while this screen isn't visible."""
        super().hideEvent(event)
        self._poll_timer.stop()

    def _on_result_activated(self, item):
        """Enter or double-click on a results row → select that product."""
        row = self.results_table.currentRow()
        if row < 0:
            return
        bc_item   = self.results_table.item(row, 0)
        desc_item = self.results_table.item(row, 1)
        if bc_item and desc_item:
            self._select(bc_item.text(), desc_item.text())

    def _on_reason_changed(self, text):
        code = text.strip().upper()
        if code in REASON_MAP:
            self.reason_desc_lbl.setText(REASON_MAP[code])
            self.reason_desc_lbl.setStyleSheet(f"color: {styles.CLR_SUCCESS_ALT}; font-size: 11px; padding-left: 4px;")
        elif code:
            self.reason_desc_lbl.setText("Unknown code")
            self.reason_desc_lbl.setStyleSheet(f"color: {styles.CLR_DANGER}; font-size: 11px; padding-left: 4px;")
        else:
            self.reason_desc_lbl.setText("")

    def _open_reason_lookup(self):
        dlg = _ReasonLookupDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_code:
            self.adj_type.setText(dlg.selected_code)
            self.adj_type.setFocus()

    def _on_search_changed(self):
        self._timer.start(500)

    def _do_search(self):
        query = self.search.text().strip()
        self.results_table.setRowCount(0)
        if len(query) < 2:
            return
        products = search_products(query)
        if not products:
            return

        barcodes = [p["barcode"] for p in products]
        soh_map = product_controller.get_soh_by_barcodes(barcodes)

        self.results_table.setUpdatesEnabled(False)
        self.results_table.setRowCount(len(products))
        for r, p in enumerate(products):
            on_hand = int(soh_map.get(p["barcode"], 0))
            self.results_table.setItem(r, 0, _item(p["barcode"]))
            self.results_table.setItem(r, 1, _item(p["description"]))
            self.results_table.setItem(r, 2, _item(p["supplier_sku"] or ""))
            self.results_table.setItem(r, 3, _item(p["dept_name"] or ""))
            self.results_table.setItem(r, 4, _item(str(on_hand), CENTER))
            sel_btn = QPushButton("Select")
            sel_btn.setFixedHeight(26)
            sel_btn.clicked.connect(
                lambda _, bc=p["barcode"], nm=p["description"]: self._select(bc, nm)
            )
            self.results_table.setCellWidget(r, 5, sel_btn)
        self.results_table.setUpdatesEnabled(True)

    def _select(self, barcode, description):
        self._selected_barcode = barcode
        self._selected_description = description
        self._render_selected_label()
        self.apply_btn.setEnabled(True)
        self.qty_spin.setFocus()
        self.qty_spin.selectAll()
        self._poll_timer.start()

    def _render_selected_label(self):
        soh = product_controller.get_soh_by_barcode(self._selected_barcode)
        on_hand = int(soh["quantity"]) if soh else 0
        self.selected_label.setText(
            f"Selected: {self._selected_description}   |   "
            f"Barcode: {self._selected_barcode}   |   Current Stock: {on_hand}"
        )
        return on_hand

    def _refresh_selected_soh(self):
        """Poll tick / external-change refresh — re-render the current selection's SOH."""
        if not self._selected_barcode:
            self._poll_timer.stop()
            return
        self._render_selected_label()

    def _on_external_stock_change(self):
        """Another screen or background sync changed stock — refresh what's on screen."""
        if self._selected_barcode:
            self._render_selected_label()
        if self.results_table.rowCount() > 0:
            self._do_search()

    def _apply(self):
        if not self._selected_barcode:
            return
        qty = self.qty_spin.value()
        if qty == 0:
            QMessageBox.warning(self, "Invalid", "Quantity cannot be zero.")
            return
        raw_code = self.adj_type.text().strip().upper()
        if raw_code in REASON_MAP:
            adj_type_val = f"{raw_code} - {REASON_MAP[raw_code]}"
        elif raw_code:
            adj_type_val = raw_code
        else:
            adj_type_val = "ADJUSTMENT"

        # Re-fetch right before confirming — closes the gap between selecting
        # a product and confirming, during which another process (POS sale)
        # could have moved the real quantity.
        self._render_selected_label()

        desc = self.selected_label.text().split("   |   ")[0].replace("Selected: ", "")
        dlg = _ConfirmAdjustDialog(
            description=desc,
            barcode=self._selected_barcode,
            qty=qty,
            reason=adj_type_val,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self.apply_btn.setEnabled(False)
        self.apply_btn.setText("Processing…")
        self.clear_btn.setEnabled(False)

        self._worker = _AdjustWorker(
            barcode=self._selected_barcode,
            qty=qty,
            adj_type=adj_type_val,
            reference=self.ref_input.text().strip() or None,
            notes=self.notes_input.text().strip() or None,
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_adjust_done)
        self._worker.error.connect(self._on_adjust_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def _on_adjust_done(self, new_qty, history_rows):
        QMessageBox.information(self, "Done",
            f"Adjustment applied.\nNew stock on hand: {new_qty}")
        self._clear_selection()
        self._populate_history(history_rows)
        self._do_search()
        self.apply_btn.setText("✓  Apply Adjustment")
        self.clear_btn.setEnabled(True)
        self.stock_changed.emit()
        stock_events.changed.emit()
        self.qty_spin.setFocus()
        self.qty_spin.selectAll()

    def _on_adjust_error(self, msg):
        QMessageBox.critical(self, "Error", msg)
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("✓  Apply Adjustment")
        self.clear_btn.setEnabled(True)

    def _clear_selection(self):
        self._selected_barcode = None
        self._selected_description = None
        self._poll_timer.stop()
        self.selected_label.setText("No product selected")
        self.apply_btn.setEnabled(False)
        self.qty_spin.setValue(0)
        self.adj_type.clear()
        self.reason_desc_lbl.setText("")
        self.ref_input.clear()
        self.notes_input.clear()

    def _load_history(self):
        rows = product_controller.get_recent_adjustments(limit=100)
        self._populate_history(rows)

    def _populate_history(self, rows):
        self.history_table.setUpdatesEnabled(False)
        self.history_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.history_table.setItem(r, 0, _item((row[0] or "")[:16]))
            self.history_table.setItem(r, 1, _item(row[1] or ""))
            self.history_table.setItem(r, 2, _item(row[2] or ""))
            self.history_table.setItem(r, 3, _item(row[3] or ""))
            qty = row[4] or 0
            qi = _item(f"{qty:+.0f}", CENTER)
            qi.setForeground(QColor(styles.CLR_SUCCESS_ALT if qty > 0 else styles.CLR_DANGER_ALT))
            self.history_table.setItem(r, 4, qi)
            self.history_table.setItem(r, 5, _item(row[5] or ""))
            self.history_table.setItem(r, 6, _item(row[6] or ""))
        self.history_table.setUpdatesEnabled(True)
