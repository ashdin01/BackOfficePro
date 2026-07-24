from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit,
    QDialog, QFrame
)
from PyQt6.QtCore import Qt, QObject, QEvent
from PyQt6.QtGui import QColor
import math
from utils.calculations import round_half_up, amount_inc_from_ex, gst_from_inclusive
import controllers.product_controller as product_ctrl
import controllers.purchase_order_controller as po_ctrl
from config.constants import PO_STATUS_RECEIVED, PO_STATUS_PARTIAL, MOVE_RECEIPT
import config.styles as styles
from utils.error_dialog import show_error
from utils.stock_events import stock_events
from views.base_view import BaseView



class _PriceChangeDialog(QDialog):
    """
    Shown when received cost differs from product cost price.
    Returns:
      .choice  = 'new'   → update product cost price permanently
               = 'promo' → receive at this price, do NOT update cost price
               = None    → cancelled
    """
    NEW   = 'new'
    PROMO = 'promo'

    def __init__(self, barcode, description, old_cost, new_cost, is_weight=False, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle("Price Change Detected")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build(barcode, description, old_cost, new_cost, is_weight)

    def _build(self, barcode, description, old_cost, new_cost, is_weight):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)
        self.setStyleSheet(f"""
            QDialog  {{ background: {styles.CLR_BG}; color: {styles.CLR_TEXT}; }}
            QLabel   {{ color: {styles.CLR_TEXT}; background: transparent; }}
            QPushButton {{
                border-radius: 4px; padding: 8px 20px;
                font-size: 13px; font-weight: bold;
            }}
            QFrame {{ color: {styles.CLR_BORDER}; }}
        """)
        title = QLabel("⚠  Price Change Detected")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {styles.CLR_AMBER};")
        layout.addWidget(title)

        info = QLabel(f"<b>{description}</b><br>"
                      f"<span style='color:{styles.CLR_MUTED};font-size:11px;'>{barcode}</span>")
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        unit_label = "per kg" if is_weight else "per unit"
        diff = new_cost - old_cost
        diff_col = styles.CLR_DANGER if diff > 0 else styles.CLR_SUCCESS
        diff_str = f"+${diff:.4f}" if diff > 0 else f"-${abs(diff):.4f}"
        price_lbl = QLabel(
            f"<table width='100%' cellpadding='3'>"
            f"<tr><td>Current cost price ({unit_label}):</td>"
            f"    <td align='right'><b>${old_cost:.4f}</b></td></tr>"
            f"<tr><td>This delivery cost ({unit_label}):</td>"
            f"    <td align='right'><b style='color:{diff_col}'>${new_cost:.4f}</b></td></tr>"
            f"<tr><td>Difference:</td>"
            f"    <td align='right'><span style='color:{diff_col}'>{diff_str}</span></td></tr>"
            f"</table>"
        )
        price_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(price_lbl)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        btn_update = QPushButton("Update Cost Price  [U]")
        btn_update.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:1px solid {styles.CLR_ACCENT_HOVER};}}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}")
        btn_promo = QPushButton("Promo Price  [P]")
        btn_promo.setStyleSheet(
            f"QPushButton{{background:#3a2e00;color:{styles.CLR_AMBER};border:1px solid {styles.CLR_AMBER};}}"
            "QPushButton:hover{background:#4a3e00;}")
        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{styles.CLR_MUTED};border:1px solid {styles.CLR_BORDER};}}"
            f"QPushButton:hover{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};}}")

        btn_update.clicked.connect(self._choose_update)
        btn_promo.clicked.connect(self._choose_promo)
        btn_cancel.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addWidget(btn_update)
        btn_row.addWidget(btn_promo)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self._btn_update = btn_update
        self._btn_promo  = btn_promo
        self._btn_cancel = btn_cancel
        btn_update.setFocus()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_U:
            self._choose_update()
        elif key == Qt.Key.Key_P:
            self._choose_promo()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            if focused == self._btn_promo:
                self._choose_promo()
            elif focused == self._btn_cancel:
                self.reject()
            else:
                self._choose_update()
        else:
            super().keyPressEvent(event)

    def _choose_update(self):
        self.choice = self.NEW
        self.accept()

    def _choose_promo(self):
        self.choice = self.PROMO
        self.accept()


class _SpinEnterFilter(QObject):
    """Press Enter in a QSpinBox/QDoubleSpinBox → move focus to next widget."""
    def __init__(self, next_widget, parent=None):
        super().__init__(parent)
        self._next = next_widget

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._next.setFocus()
                self._next.selectAll()
                return True
        return False


class _CostEnterFilter(QObject):
    """
    Enter key in cost_input:
      - cost unchanged → jump to next row's qty spinner
      - cost changed   → open _PriceChangeDialog
                          'new'   → update promo_cb=unchecked
                          'promo' → tick promo_cb
                         then jump to next row's qty spinner
    """
    def __init__(self, cost_input, original_cost, barcode, description,
                 row_index, inputs_ref, promo_cb, parent_widget, is_weight=False):
        super().__init__(cost_input)
        self._cost       = cost_input
        self._orig       = original_cost
        self._bc         = barcode
        self._desc       = description
        self._row        = row_index
        self._inputs     = inputs_ref
        self._promo      = promo_cb
        self._parent     = parent_widget
        self._is_weight  = is_weight

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._handle_enter()
                return True
        return False

    def _handle_enter(self):
        new_cost = self._cost.value()
        if new_cost > 0 and abs(new_cost - self._orig) > 0.0001:
            dlg = _PriceChangeDialog(
                barcode=self._bc,
                description=self._desc,
                old_cost=self._orig,
                new_cost=new_cost,
                is_weight=self._is_weight,
                parent=self._parent,
            )
            result = dlg.exec()
            if result == QDialog.DialogCode.Rejected or dlg.choice is None:
                self._cost.setValue(self._orig)
                self._cost.setFocus()
                self._cost.selectAll()
                return
            if dlg.choice == _PriceChangeDialog.PROMO:
                self._promo.setChecked(True)
            else:
                self._promo.setChecked(False)

        # Jump to next row's qty spinner (index 2 in _inputs tuple)
        next_row = self._row + 1
        if next_row < len(self._inputs):
            next_qty = self._inputs[next_row][2]
            next_qty.setFocus()
            next_qty.selectAll()


class POReceive(BaseView):
    def __init__(self, po_id, on_save=None):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self.setWindowTitle("Receive Stock")
        self.setMinimumSize(1600, 620)
        self.resize(1750, 750)
        self.charges_table = None
        self._build_ui()
        self.load()

    # ── Theme colours ─────────────────────────────────────────────────
    BG       = styles.CLR_BG
    BG_ALT   = styles.CLR_BG_PANEL
    FG       = styles.CLR_TEXT
    FG_DIM   = styles.CLR_MUTED
    BORDER   = styles.CLR_BORDER
    SEL_BG   = styles.CLR_ACCENT
    AMBER_BG = "#3a2e00"
    AMBER_FG = styles.CLR_AMBER

    def _cell(self, text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        item.setForeground(QColor(self.FG))
        item.setBackground(QColor(self.BG))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.setStyleSheet(f"""
            QWidget          {{ background: {self.BG}; color: {self.FG}; }}
            QLabel           {{ color: {self.FG}; background: transparent; }}
            QTableWidget     {{ background: {self.BG}; color: {self.FG};
                               gridline-color: {self.BORDER};
                               selection-background-color: {self.SEL_BG};
                               border: 1px solid {self.BORDER}; }}
            QTableWidget::item {{ background: {self.BG}; color: {self.FG}; }}
            QTableWidget::item:alternate {{ background: {self.BG_ALT}; color: {self.FG}; }}
            QTableWidget::item:selected {{ background: {self.SEL_BG}; color: {self.FG}; }}
            QHeaderView::section {{ background: {self.BG_ALT}; color: {self.FG};
                                   border: 1px solid {self.BORDER}; padding: 4px;
                                   font-weight: bold; }}
            QSpinBox, QDoubleSpinBox {{
                background: {self.BG_ALT}; color: {self.FG};
                border: 1px solid {self.BORDER}; border-radius: 3px; padding: 2px 4px;
            }}
            QCheckBox        {{ color: {self.FG}; background: transparent; }}
            QPushButton      {{ background: {self.BG_ALT}; color: {self.FG};
                               border: 1px solid {self.BORDER}; border-radius: 4px;
                               padding: 4px 12px; }}
            QPushButton:hover {{ background: {self.BORDER}; }}
        """)

        self.header = QLabel()
        layout.addWidget(self.header)

        # ── Supplier Invoice Number (required) ────────────────────────
        inv_row = QHBoxLayout()
        inv_lbl = QLabel("Supplier Invoice #:")
        inv_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        inv_row.addWidget(inv_lbl)
        self.supplier_invoice_input = QLineEdit()
        self.supplier_invoice_input.setPlaceholderText("Enter supplier invoice number  (required)")
        self.supplier_invoice_input.setFixedWidth(300)
        self.supplier_invoice_input.setStyleSheet(
            f"QLineEdit {{ background: {self.BG_ALT}; color: {self.FG};"
            f" border: 1px solid {self.BORDER}; border-radius: 4px; padding: 4px 8px;"
            f" font-size: 13px; }}"
            f"QLineEdit:focus {{ border-color: {styles.CLR_ACCENT_HOVER}; }}"
        )
        inv_row.addWidget(self.supplier_invoice_input)
        inv_row.addStretch()
        layout.addLayout(inv_row)

        note = QLabel(
            "💡  Enter units received and cost per unit.  "
            "For weighed items ⚖ also enter total weight — "
            "Line Total = Weight (kg) × Cost per kg.  "
            "Stock on hand always adjusts by number of items.  "
            "☑ Promo = cost price will NOT be updated in the product master."
        )
        note.setStyleSheet("color: #FFA500; font-size: 11px; padding: 4px 0;")
        layout.addWidget(note)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ alternate-background-color: {styles.CLR_BG_PANEL}; background: {styles.CLR_BG}; }}"
        )
        # 10 columns — weight column (col 6) is hidden for non-weighed items
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Pack Size",
            "Ordered (Units)", "Already Received",
            "Receiving Now",
            "Weight (kg)",       # col 6 — weighed items only
            "Cost ($/kg or unit) ex. GST", "Cost inc. Tax", "Promo?", "Line Total ex. GST", "Line Total inc. Tax"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]:
            hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(2,  80)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 110)
        self.table.setColumnWidth(6, 100)   # Weight (kg)
        self.table.setColumnWidth(7, 120)   # Cost
        self.table.setColumnWidth(8, 110)   # Cost inc. Tax
        self.table.setColumnWidth(9,  70)   # Promo
        self.table.setColumnWidth(10, 110)  # Line Total ex. GST
        self.table.setColumnWidth(11, 120)  # Line Total inc. Tax
        layout.addWidget(self.table)

        self.total_label = QLabel()
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.total_label)

        # ── Additional Charges ────────────────────────────────────
        charges_header = QHBoxLayout()
        charges_lbl = QLabel("Additional Charges  (freight, fuel levy, surcharges etc.)")
        charges_lbl.setStyleSheet(f"color: {styles.CLR_MUTED}; font-size: 11px; font-weight: bold;")
        charges_header.addWidget(charges_lbl)
        charges_header.addStretch()
        btn_add_charge = QPushButton("+ Add Charge")
        btn_add_charge.setFixedHeight(28)
        btn_add_charge.setFixedWidth(110)
        btn_add_charge.clicked.connect(self._add_charge)
        btn_remove_charge = QPushButton("Remove")
        btn_remove_charge.setFixedHeight(28)
        btn_remove_charge.setFixedWidth(80)
        btn_remove_charge.clicked.connect(self._remove_charge)
        charges_header.addWidget(btn_add_charge)
        charges_header.addWidget(btn_remove_charge)
        layout.addLayout(charges_header)

        self.charges_table = QTableWidget()
        self.charges_table.setColumnCount(3)
        self.charges_table.setHorizontalHeaderLabels(["Description", "Tax Type", "Amount inc. Tax"])
        self.charges_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.charges_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.charges_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.charges_table.setColumnWidth(1, 130)
        self.charges_table.setColumnWidth(2, 150)
        self.charges_table.setFixedHeight(110)
        self.charges_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.charges_table.itemChanged.connect(self._update_total)
        layout.addWidget(self.charges_table)

        btns = QHBoxLayout()
        btn_receive_all = QPushButton("Receive All")
        btn_receive_all.setFixedHeight(35)
        btn_receive_all.setToolTip("Set all Receiving Now quantities to their full remaining amounts")
        btn_receive_all.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;font-weight:bold;"
            f"border:none;border-radius:4px;padding:0 16px;}}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
        )
        btn_receive_all.clicked.connect(self._receive_all)

        btn_receive = QPushButton("Confirm Receipt")
        btn_receive.setFixedHeight(35)
        btn_receive.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_SUCCESS_DARK};color:white;font-weight:bold;"
            f"border:none;border-radius:4px;padding:0 16px;}}"
            f"QPushButton:hover{{background:{styles.CLR_SUCCESS_HOVER};}}"
        )
        btn_receive.clicked.connect(self._confirm)

        btn_close = QPushButton("Close")
        btn_close.setFixedHeight(35)
        btn_close.clicked.connect(self.close)

        btns.addStretch()
        btns.addWidget(btn_receive_all)
        btns.addWidget(btn_receive)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _add_charge(self):
        from PyQt6.QtWidgets import QComboBox
        r = self.charges_table.rowCount()
        self.charges_table.blockSignals(True)
        self.charges_table.insertRow(r)
        self.charges_table.setItem(r, 0, QTableWidgetItem("Freight"))
        tax_combo = QComboBox()
        tax_combo.addItem("GST (10%)", 10.0)
        tax_combo.addItem("GST Free (0%)", 0.0)
        tax_combo.currentIndexChanged.connect(self._update_total)
        self.charges_table.setCellWidget(r, 1, tax_combo)
        amt_item = QTableWidgetItem("0.00")
        amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.charges_table.setItem(r, 2, amt_item)
        self.charges_table.blockSignals(False)
        self._update_total()

    def _remove_charge(self):
        row = self.charges_table.currentRow()
        if row >= 0:
            self.charges_table.removeRow(row)
            self._update_total()

    def _open_product(self, index):
        row = index.row()
        barcode_item = self.table.item(row, 0)
        if not barcode_item:
            return
        barcode = barcode_item.text().strip()
        if not barcode:
            return
        from views.products.product_edit import ProductEdit
        self._product_win = ProductEdit(barcode=barcode, on_save=self.load)
        self._product_win.show()
        self._product_win.raise_()

    def _load(self):
        po = po_ctrl.get_po_by_id(self.po_id)
        self.setWindowTitle(f"Receive: {po['po_number']}")
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} "
            f"— Status: <b>{po['status']}</b>"
        )
        existing_inv = po['supplier_invoice_number'] or ''
        if existing_inv:
            self.supplier_invoice_input.setText(existing_inv)
        self.lines = po_ctrl.get_po_lines(self.po_id)
        self.table.setRowCount(0)

        # Tuple stored per row:
        # (line, pack_qty, qty_input, cost_input, promo_checkbox, lt_item,
        #  remaining_units, is_variable_weight, weight_input)
        self._inputs = []

        for line in self.lines:
            if line['is_note']:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)

            product      = product_ctrl.get_product_by_barcode(line['barcode'])
            pack_qty     = int(product['pack_qty']) if product and product['pack_qty'] else 1
            pack_unit    = (product['pack_unit'] or 'EA') if product else 'EA'
            current_cost = float(product['cost_price']) if product else 0.0
            is_vw        = bool(product['variable_weight']) if product else False
            tax_rate     = float(product['tax_rate']) if product and product['tax_rate'] else 0.0

            ordered_cartons  = int(line['ordered_qty'])
            ordered_units    = ordered_cartons * pack_qty
            received_cartons = int(line['received_qty'])
            received_units   = received_cartons * pack_qty
            remaining_units  = ordered_units - received_units

            # ── Static cells ─────────────────────────────────────────
            self.table.setItem(r, 0, self._cell(line['barcode'], Qt.AlignmentFlag.AlignCenter))
            # Description — append ⚖ indicator for weighed items
            desc_text = f"⚖ {line['description']}" if is_vw else line['description']
            self.table.setItem(r, 1, self._cell(desc_text))
            self.table.setItem(r, 2, self._cell(
                f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit,
                Qt.AlignmentFlag.AlignCenter))
            self.table.setItem(r, 3, self._cell(str(ordered_units),  Qt.AlignmentFlag.AlignCenter))
            self.table.setItem(r, 4, self._cell(str(received_units), Qt.AlignmentFlag.AlignCenter))

            # ── Col 5: Receiving Now (always items, always integer) ──
            qty_input = QSpinBox()
            qty_input.setMinimum(0)
            qty_input.setMaximum(max(0, remaining_units))
            qty_input.setSingleStep(pack_qty)
            qty_input.setValue(0)
            self.table.setCellWidget(r, 5, qty_input)

            # ── Col 6: Weight (kg) — weighed items only ──────────────
            weight_input = QDoubleSpinBox()
            weight_input.setMinimum(0.0)
            weight_input.setMaximum(999999.0)
            weight_input.setDecimals(3)
            weight_input.setSuffix(" kg")
            weight_input.setValue(0.0)
            weight_input.setToolTip("Total weight received for this line")

            if is_vw:
                self.table.setCellWidget(r, 6, weight_input)
            else:
                # Hide the weight column cell for non-weighed items
                placeholder = self._cell("—", Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, 6, placeholder)

            # ── Col 7: Cost per unit or per kg ───────────────────────
            cost_input = QDoubleSpinBox()
            cost_input.setMinimum(0)
            cost_input.setMaximum(999999)
            cost_input.setDecimals(4)
            cost_input.setValue(current_cost if current_cost > 0 else line['unit_cost'])
            if is_vw:
                cost_input.setToolTip(
                    "Cost per kg — Line Total = Weight × Cost/kg.  "
                    "Saved back to product master (unless Promo)."
                )
            else:
                cost_input.setToolTip(
                    "Cost per unit — updates product cost price on confirm (unless Promo is ticked)"
                )
            self.table.setCellWidget(r, 7, cost_input)

            # ── Col 8: Promo checkbox ────────────────────────────────
            promo_cb = QCheckBox()
            try:
                promo_cb.setChecked(bool(line['is_promo']))
            except (IndexError, KeyError):
                promo_cb.setChecked(False)
            promo_cb.setToolTip(
                "Promo price — stock will be received at this cost\n"
                "but the product master cost price will NOT be updated."
            )
            cb_container = QWidget()
            cb_lay = QHBoxLayout(cb_container)
            cb_lay.addWidget(promo_cb)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(r, 9, cb_container)
            promo_cb.stateChanged.connect(lambda _, row=r: self._refresh_promo_colour(row))

            # ── Col 10: Line Total ex. GST — read only ─────────────────
            lt_item = self._cell("$0.00", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 10, lt_item)
            # ── Col 11: Line Total inc. Tax — read only ──────────────────
            lt_inc_item = self._cell("$0.00", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lt_inc_item.setForeground(__import__('PyQt6.QtGui', fromlist=['QColor']).QColor(styles.CLR_SUCCESS_ALT) if tax_rate > 0 else __import__('PyQt6.QtGui', fromlist=['QColor']).QColor('#aaaaaa'))
            self.table.setItem(r, 11, lt_inc_item)
            # ── Col 10: Cost inc. GST — read only ────────────────────
            cost_inc = current_cost * (1 + tax_rate / 100)
            cost_inc_item = self._cell(f"${cost_inc:.4f}", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cost_inc_item.setForeground(__import__('PyQt6.QtGui', fromlist=['QColor']).QColor(styles.CLR_SUCCESS_ALT) if tax_rate > 0 else __import__('PyQt6.QtGui', fromlist=['QColor']).QColor('#aaaaaa'))
            self.table.setItem(r, 8, cost_inc_item)

            # ── Signal connections ────────────────────────────────────
            qty_input.valueChanged.connect(lambda _, row=r: self._refresh_line(row))
            cost_input.valueChanged.connect(lambda _, row=r: self._refresh_line(row))
            if is_vw:
                weight_input.valueChanged.connect(lambda _, row=r: self._refresh_line(row))

            # ── Enter key navigation ──────────────────────────────────
            if is_vw:
                # qty → weight → cost → next row qty
                qty_filter = _SpinEnterFilter(weight_input, qty_input)
                qty_input.installEventFilter(qty_filter)
                weight_filter = _SpinEnterFilter(cost_input, weight_input)
                weight_input.installEventFilter(weight_filter)
            else:
                # qty → cost → next row qty
                qty_filter = _SpinEnterFilter(cost_input, qty_input)
                qty_input.installEventFilter(qty_filter)

            cost_input.installEventFilter(
                _CostEnterFilter(
                    cost_input=cost_input,
                    original_cost=current_cost,
                    barcode=line['barcode'],
                    description=line['description'],
                    row_index=r,
                    inputs_ref=self._inputs,
                    promo_cb=promo_cb,
                    parent_widget=self,
                    is_weight=is_vw,
                )
            )

            self._inputs.append((
                line, pack_qty, qty_input, cost_input, promo_cb,
                lt_item, remaining_units, is_vw, weight_input, tax_rate, lt_inc_item
            ))
            self._refresh_line(r)

        self._update_total()

        # Auto-focus first Receiving Now spinner
        if self._inputs:
            first_qty = self._inputs[0][2]
            self.table.setCurrentCell(0, 5)
            first_qty.setFocus()
            first_qty.selectAll()

    def _refresh_promo_colour(self, row):
        cb = self._inputs[row][4] if row < len(self._inputs) else None
        is_promo = cb and cb.isChecked()
        for col in [0, 1, 2, 3, 4, 10, 11]:
            item = self.table.item(row, col)
            if item:
                if is_promo:
                    item.setBackground(QColor(self.AMBER_BG))
                    item.setForeground(QColor(self.AMBER_FG))
                else:
                    item.setBackground(QColor(self.BG))
                    item.setForeground(QColor(self.FG))

    def _refresh_line(self, row):
        if row >= len(self._inputs):
            return
        line, pack_qty, qty_input, cost_input, promo_cb, lt_item, \
            remaining_units, is_vw, weight_input, tax_rate, lt_inc_item = self._inputs[row]

        cost = cost_input.value()

        if is_vw:
            weight     = weight_input.value()
            line_total = weight * cost
        else:
            qty        = qty_input.value()
            line_total = qty * cost

        lt_item.setText(f"${round_half_up(line_total):.2f}")
        line_total_inc = amount_inc_from_ex(line_total, tax_rate)
        lt_inc_item.setText(f"${round_half_up(line_total_inc):.2f}")
        from PyQt6.QtGui import QColor
        lt_inc_item.setForeground(QColor(styles.CLR_SUCCESS_ALT) if tax_rate > 0 else QColor('#aaaaaa'))
        cost_inc = amount_inc_from_ex(cost, tax_rate)
        cost_inc_item = self.table.item(row, 8)
        if cost_inc_item:
            cost_inc_item.setText(f"${cost_inc:.4f}")
            cost_inc_item.setForeground(QColor(styles.CLR_SUCCESS_ALT) if tax_rate > 0 else QColor('#aaaaaa'))
        self._refresh_promo_colour(row)
        self._update_total()

    def _update_total(self):
        total_inc = 0.0
        gst_total = 0.0
        promo_total = 0.0
        for entry in self._inputs:
            tax_rate = entry[9] if len(entry) > 9 else 0.0
            lt_inc_item = entry[10] if len(entry) > 10 else None
            _, _, _, _, promo_cb, lt_item = entry[0], entry[1], entry[2], entry[3], entry[4], entry[5]
            try:
                ex_val = float(lt_item.text().replace("$", "").replace(",", ""))
                inc_val = float(lt_inc_item.text().replace("$", "").replace(",", "")) if lt_inc_item else ex_val
                total_inc += inc_val
                gst_total += inc_val - ex_val
                if promo_cb.isChecked():
                    promo_total += inc_val
            except (ValueError, AttributeError):
                pass
        # Additional charges
        if self.charges_table is not None:
            for cr in range(self.charges_table.rowCount()):
                try:
                    amt_item = self.charges_table.item(cr, 2)
                    if not amt_item:
                        continue
                    amt = float(amt_item.text().replace("$", "").replace(",", ""))
                    tax_combo = self.charges_table.cellWidget(cr, 1)
                    charge_tax = tax_combo.currentData() if tax_combo else 0.0
                    total_inc += amt
                    if charge_tax > 0:
                        gst_total += gst_from_inclusive(amt, charge_tax)
                except (ValueError, AttributeError):
                    pass
        subtotal = round_half_up(total_inc - gst_total)
        gst = round_half_up(gst_total)
        total_inc = round_half_up(total_inc)
        promo_str = ""
        if promo_total > 0:
            promo_str = f"&nbsp;&nbsp;&nbsp;<span style='color:{styles.CLR_AMBER};font-size:11px;'>(includes <b>${promo_total:.2f}</b> promo — cost price NOT updated)</span>"
        self.total_label.setText(
            f"Subtotal ex. GST: <b>${subtotal:.2f}</b>"
            f"&nbsp;&nbsp;&nbsp;GST: <b>${gst:.2f}</b>"
            f"&nbsp;&nbsp;&nbsp;Invoice Total inc. GST: <b style='color:{styles.CLR_SUCCESS_ALT}'>${total_inc:.2f}</b>"
            f"{promo_str}"
        )

    def _receive_all(self):
        """Fill all Receiving Now spinners with full remaining quantities."""
        for entry in self._inputs:
            line, pack_qty, qty_input, cost_input, promo_cb, \
                lt_item, remaining_units, is_vw, weight_input, tax_rate, lt_inc_item = entry
            qty_input.setValue(remaining_units)

    def _confirm(self):
        supplier_inv = self.supplier_invoice_input.text().strip()
        if not supplier_inv:
            self.supplier_invoice_input.setStyleSheet(
                f"QLineEdit {{ background: {self.BG_ALT}; color: {self.FG};"
                f" border: 2px solid {styles.CLR_DANGER}; border-radius: 4px; padding: 4px 8px;"
                f" font-size: 13px; }}"
            )
            self.supplier_invoice_input.setFocus()
            QMessageBox.warning(
                self, "Invoice Number Required",
                "Please enter the supplier invoice number before confirming receipt."
            )
            return

        # Reset border if previously highlighted
        self.supplier_invoice_input.setStyleSheet(
            f"QLineEdit {{ background: {self.BG_ALT}; color: {self.FG};"
            f" border: 1px solid {self.BORDER}; border-radius: 4px; padding: 4px 8px;"
            f" font-size: 13px; }}"
            f"QLineEdit:focus {{ border-color: {styles.CLR_ACCENT_HOVER}; }}"
        )

        po = po_ctrl.get_po_by_id(self.po_id)
        po_number = po['po_number']

        if po['status'] in ('RECEIVED', 'REVERSED', 'CANCELLED'):
            QMessageBox.warning(
                self, "Cannot Receive",
                f"{po_number} has status '{po['status']}' and cannot be received again."
            )
            return

        promo_count = sum(
            1 for entry in self._inputs
            if entry[4].isChecked() and entry[2].value() > 0
        )
        msg = "Receive stock and update cost prices?"
        if promo_count:
            msg = (f"Receive stock?\n\n"
                   f"⚠  {promo_count} promo line(s) — stock will be received "
                   f"but cost price will NOT be updated for those items.")
        reply = QMessageBox.question(self, "Confirm Receipt", msg)
        if reply != QMessageBox.StandardButton.Yes:
            return

        line_receipts = []
        all_received  = True

        for entry in self._inputs:
            line, pack_qty, qty_input, cost_input, promo_cb, \
                lt_item, remaining_units, is_vw, weight_input, tax_rate, lt_inc_item = entry

            qty      = qty_input.value()
            cost     = cost_input.value()
            weight   = weight_input.value() if is_vw else 0.0
            is_promo = promo_cb.isChecked()

            cartons = max(1, math.ceil(qty / pack_qty)) if qty > 0 else 0
            total_received_cartons = line['received_qty'] + cartons
            if total_received_cartons < line['ordered_qty']:
                all_received = False

            if qty > 0:
                line_receipts.append({
                    'line_id':             line['id'],
                    'barcode':             line['barcode'],
                    'new_received_qty':    line['received_qty'] + cartons,
                    'new_received_weight': (line['received_weight'] or 0) + weight,
                    'actual_cost':         cost if cost > 0 else None,
                    'unit_cost':           cost if cost > 0 else None,
                    'is_promo':            is_promo,
                    'qty_units':           qty,
                })

        status = PO_STATUS_RECEIVED if all_received else PO_STATUS_PARTIAL

        # Collect additional charges
        charges = []
        if self.charges_table is not None:
            for cr in range(self.charges_table.rowCount()):
                try:
                    desc_item = self.charges_table.item(cr, 0)
                    amt_item  = self.charges_table.item(cr, 2)
                    tax_combo = self.charges_table.cellWidget(cr, 1)
                    if not amt_item:
                        continue
                    amt      = float(amt_item.text().replace("$", "").replace(",", "") or 0)
                    tax_rate = tax_combo.currentData() if tax_combo else 0.0
                    charges.append({
                        'description':   (desc_item.text() if desc_item else '') or 'Charge',
                        'tax_rate':      tax_rate,
                        'amount_inc_tax': amt,
                    })
                except (ValueError, AttributeError):
                    pass

        try:
            po_ctrl.receive_po_atomic(self.po_id, po_number, line_receipts, status,
                                      supplier_invoice_number=supplier_inv,
                                      charges=charges)
        except Exception as exc:
            show_error(self, "Receipt failed — no changes were saved.", exc, title="Receipt Failed")
            return

        if self.on_save:
            self.on_save()
        stock_events.changed.emit()

        QMessageBox.information(self, "Done", f"Stock received. PO status: {status}")
        self.close()
