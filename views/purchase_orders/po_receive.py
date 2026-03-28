from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpinBox, QDoubleSpinBox, QCheckBox,
    QDialog, QFrame
)
from PyQt6.QtCore import Qt, QObject, QEvent
from PyQt6.QtGui import QColor
import math
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.stock_on_hand as stock_model
import models.product as product_model
from config.constants import PO_STATUS_RECEIVED, PO_STATUS_PARTIAL, MOVE_RECEIPT


def _ensure_promo_column():
    """Add is_promo column to po_lines if it doesn't exist yet. Safe to call every run."""
    from database.connection import get_connection
    conn = get_connection()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(po_lines)").fetchall()]
        if 'is_promo' not in cols:
            conn.execute("ALTER TABLE po_lines ADD COLUMN is_promo INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    finally:
        conn.close()


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

    def __init__(self, barcode, description, old_cost, new_cost, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle("Price Change Detected")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build(barcode, description, old_cost, new_cost)

    def _build(self, barcode, description, old_cost, new_cost):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        self.setStyleSheet("""
            QDialog  { background: #1a2332; color: #e6edf3; }
            QLabel   { color: #e6edf3; background: transparent; }
            QPushButton {
                border-radius: 4px; padding: 8px 20px;
                font-size: 13px; font-weight: bold;
            }
            QFrame { color: #2a3a4a; }
        """)

        # Header
        title = QLabel("⚠  Price Change Detected")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFB300;")
        layout.addWidget(title)

        # Product info
        info = QLabel(f"<b>{description}</b><br>"
                      f"<span style='color:#8b949e;font-size:11px;'>{barcode}</span>")
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Price comparison
        diff = new_cost - old_cost
        diff_col = "#f85149" if diff > 0 else "#3fb950"
        diff_str = f"+${diff:.4f}" if diff > 0 else f"-${abs(diff):.4f}"
        price_lbl = QLabel(
            f"<table width='100%' cellpadding='3'>"
            f"<tr><td>Current cost price:</td>"
            f"    <td align='right'><b>${old_cost:.4f}</b></td></tr>"
            f"<tr><td>This delivery cost:</td>"
            f"    <td align='right'><b style='color:{diff_col}'>${new_cost:.4f}</b></td></tr>"
            f"<tr><td>Difference:</td>"
            f"    <td align='right'><span style='color:{diff_col}'>{diff_str}</span></td></tr>"
            f"</table>"
        )
        price_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(price_lbl)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # Three action buttons
        btn_update = QPushButton("Update Cost Price  [U]")
        btn_update.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:1px solid #1976d2;}"
            "QPushButton:hover{background:#1976d2;}")

        btn_promo = QPushButton("Promo Price  [P]")
        btn_promo.setStyleSheet(
            "QPushButton{background:#3a2e00;color:#FFB300;border:1px solid #FFB300;}"
            "QPushButton:hover{background:#4a3e00;}")

        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setStyleSheet(
            "QPushButton{background:transparent;color:#8b949e;border:1px solid #2a3a4a;}"
            "QPushButton:hover{background:#1e2a38;color:#e6edf3;}")

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

        # Store button refs for Enter-key handling
        self._btn_update = btn_update
        self._btn_promo  = btn_promo
        self._btn_cancel = btn_cancel

        # Default focus on Update Cost Price
        btn_update.setFocus()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key in (Qt.Key.Key_U,):
            self._choose_update()
        elif key in (Qt.Key.Key_P,):
            self._choose_promo()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Fire whichever button currently has focus
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
      - cost unchanged → jump straight to next row's qty spinner
      - cost changed   → open _PriceChangeDialog
                          'new'   → update promo_cb=unchecked (cost will be written)
                          'promo' → tick promo_cb (cost will NOT be written)
                         then jump to next row's qty spinner
    """
    def __init__(self, cost_input, original_cost, barcode, description,
                 row_index, inputs_ref, promo_cb, parent_widget):
        super().__init__(cost_input)
        self._cost    = cost_input
        self._orig    = original_cost
        self._bc      = barcode
        self._desc    = description
        self._row     = row_index
        self._inputs  = inputs_ref   # live reference — grows as rows are added
        self._promo   = promo_cb
        self._parent  = parent_widget

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._handle_enter()
                return True
        return False

    def _handle_enter(self):
        new_cost = self._cost.value()
        # Only prompt if a cost was entered and it differs from the product master
        if new_cost > 0 and abs(new_cost - self._orig) > 0.0001:
            dlg = _PriceChangeDialog(
                barcode=self._bc,
                description=self._desc,
                old_cost=self._orig,
                new_cost=new_cost,
                parent=self._parent,
            )
            result = dlg.exec()
            if result == QDialog.DialogCode.Rejected or dlg.choice is None:
                # Cancelled — stay on cost field, restore original value
                self._cost.setValue(self._orig)
                self._cost.setFocus()
                self._cost.selectAll()
                return
            if dlg.choice == _PriceChangeDialog.PROMO:
                self._promo.setChecked(True)
            else:
                self._promo.setChecked(False)   # new permanent cost
        # Jump to next row's qty spinner (col index 2 in _inputs tuple)
        next_row = self._row + 1
        if next_row < len(self._inputs):
            next_qty = self._inputs[next_row][2]
            next_qty.setFocus()
            next_qty.selectAll()


class POReceive(QWidget):
    def __init__(self, po_id, on_save=None):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self.setWindowTitle("Receive Stock")
        self.setMinimumSize(1200, 560)
        _ensure_promo_column()   # migrate DB on first run, no-op after that
        self._build_ui()
        self._load()

    # ── Theme colours (match rest of BackOfficePro) ──────────────────
    BG       = "#1a2332"
    BG_ALT   = "#1e2a38"
    FG       = "#e6edf3"
    FG_DIM   = "#8b949e"
    BORDER   = "#2a3a4a"
    SEL_BG   = "#1565c0"
    AMBER_BG = "#3a2e00"
    AMBER_FG = "#FFB300"

    def _cell(self, text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
        """Create a pre-styled read-only table item."""
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        item.setForeground(QColor(self.FG))
        item.setBackground(QColor(self.BG))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Dark theme — match the rest of BackOfficePro
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
            QPushButton:hover {{ background: #2a3a4a; }}
        """)

        self.header = QLabel()
        layout.addWidget(self.header)

        note = QLabel(
            "💡  Enter units received and item cost per unit.  "
            "Line Total = Receiving Now × Item Cost $.  "
            "☑ Promo = cost price will NOT be updated in the product master."
        )
        note.setStyleSheet("color: #FFA500; font-size: 11px; padding: 4px 0;")
        layout.addWidget(note)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { alternate-background-color: #1e2a38; background: #1a2332; }"
        )
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Pack Size",
            "Ordered (Units)", "Already Received",
            "Receiving Now", "Item Cost $", "Promo?", "Line Total $"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 2, 3, 4, 5, 6, 7, 8]:
            hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 110)
        self.table.setColumnWidth(6, 110)
        self.table.setColumnWidth(7, 70)   # Promo checkbox col
        self.table.setColumnWidth(8, 110)
        layout.addWidget(self.table)

        self.total_label = QLabel()
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.total_label)

        btns = QHBoxLayout()
        btn_receive = QPushButton("Confirm Receipt")
        btn_receive.setFixedHeight(35)
        btn_receive.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;font-weight:bold;"
            "border:none;border-radius:4px;padding:0 16px;}"
            "QPushButton:hover{background:#388e3c;}"
        )
        btn_receive.clicked.connect(self._confirm)
        btn_close = QPushButton("Close")
        btn_close.setFixedHeight(35)
        btn_close.clicked.connect(self.close)
        btns.addStretch()
        btns.addWidget(btn_receive)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _load(self):
        po = po_model.get_by_id(self.po_id)
        self.setWindowTitle(f"Receive: {po['po_number']}")
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} "
            f"— Status: <b>{po['status']}</b>"
        )
        self.lines = lines_model.get_by_po(self.po_id)
        self.table.setRowCount(0)
        # (line, pack_qty, qty_spinbox, cost_spinbox, promo_checkbox, line_total_item)
        self._inputs = []

        for line in self.lines:
            r = self.table.rowCount()
            self.table.insertRow(r)

            product   = product_model.get_by_barcode(line['barcode'])
            pack_qty  = int(product['pack_qty']) if product and product['pack_qty'] else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
            current_cost = float(product['cost_price']) if product else 0.0

            ordered_cartons  = int(line['ordered_qty'])
            ordered_units    = ordered_cartons * pack_qty
            received_cartons = int(line['received_qty'])
            received_units   = received_cartons * pack_qty
            remaining_units  = ordered_units - received_units

            # Barcode
            self.table.setItem(r, 0, self._cell(line['barcode'], Qt.AlignmentFlag.AlignCenter))

            # Description
            self.table.setItem(r, 1, self._cell(line['description']))

            # Pack size
            self.table.setItem(r, 2, self._cell(
                f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit,
                Qt.AlignmentFlag.AlignCenter))

            # Ordered units
            self.table.setItem(r, 3, self._cell(str(ordered_units), Qt.AlignmentFlag.AlignCenter))

            # Already received
            self.table.setItem(r, 4, self._cell(str(received_units), Qt.AlignmentFlag.AlignCenter))

            # Receiving Now spinner
            qty_input = QSpinBox()
            qty_input.setMinimum(0)
            qty_input.setMaximum(99999)
            qty_input.setSingleStep(pack_qty)
            qty_input.setValue(remaining_units)
            self.table.setCellWidget(r, 5, qty_input)

            # Item Cost $ spinner
            cost_input = QDoubleSpinBox()
            cost_input.setMinimum(0)
            cost_input.setMaximum(999999)
            cost_input.setDecimals(4)
            cost_input.setPrefix("")
            cost_input.setValue(current_cost if current_cost > 0 else line['unit_cost'])
            cost_input.setToolTip("Cost per unit — updates product cost price on confirm (unless Promo is ticked)")
            self.table.setCellWidget(r, 6, cost_input)

            # ── Promo checkbox ──────────────────────────────────────────────
            promo_cb = QCheckBox()
            try:
                promo_cb.setChecked(bool(line['is_promo']))
            except (IndexError, KeyError):
                promo_cb.setChecked(False)
            promo_cb.setToolTip(
                "Promo price — stock will be received at this cost\n"
                "but the product master cost price will NOT be updated."
            )
            # Centre the checkbox in its cell
            cb_container = QWidget()
            cb_lay = QHBoxLayout(cb_container)
            cb_lay.addWidget(promo_cb)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(r, 7, cb_container)
            promo_cb.stateChanged.connect(lambda _, row=r: self._refresh_promo_colour(row))
            # ────────────────────────────────────────────────────────────────

            # Line Total $ — read only
            lt_item = self._cell("$0.00", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 8, lt_item)

            qty_input.valueChanged.connect(lambda _, row=r: self._refresh_line(row))
            cost_input.valueChanged.connect(lambda _, row=r: self._refresh_line(row))

            # Enter in qty_input → jump to cost_input (and select all)
            qty_filter = _SpinEnterFilter(cost_input, qty_input)
            qty_input.installEventFilter(qty_filter)

            # Enter in cost_input → check price, show dialog if changed, then next row
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
                )
            )

            self._inputs.append((line, pack_qty, qty_input, cost_input, promo_cb, lt_item))
            self._refresh_line(r)

        self._update_total()

        # Auto-focus the first "Receiving Now" spinner
        if self._inputs:
            first_qty = self._inputs[0][2]   # index 2 = qty_input
            self.table.setCurrentCell(0, 5)
            first_qty.setFocus()
            first_qty.selectAll()

    def _get_promo_cb(self, row):
        """Return the QCheckBox from the centring container widget."""
        container = self.table.cellWidget(row, 7)
        if container:
            for child in container.children():
                if isinstance(child, QCheckBox):
                    return child
        return None

    def _refresh_promo_colour(self, row):
        """Highlight the entire row in amber when Promo is ticked."""
        cb = self._get_promo_cb(row)
        is_promo = cb and cb.isChecked()
        for col in [0, 1, 2, 3, 4, 8]:
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
        line, pack_qty, qty_input, cost_input, promo_cb, lt_item = self._inputs[row]
        qty  = qty_input.value()
        cost = cost_input.value()
        lt_item.setText(f"${qty * cost:.2f}")
        self._refresh_promo_colour(row)
        self._update_total()

    def _update_total(self):
        total = 0.0
        promo_total = 0.0
        for idx, (line, pack_qty, qty_input, cost_input, promo_cb, lt_item) in enumerate(self._inputs):
            try:
                val = float(lt_item.text().replace("$", "").replace(",", ""))
                total += val
                if promo_cb.isChecked():
                    promo_total += val
            except (ValueError, AttributeError):
                pass

        if promo_total > 0:
            self.total_label.setText(
                f"<b>Receipt Total: ${total:.2f}</b>"
                f"&nbsp;&nbsp;&nbsp;<span style='color:#FFB300;font-size:11px;'>"
                f"(includes <b>${promo_total:.2f}</b> promo — cost price NOT updated)</span>"
            )
        else:
            self.total_label.setText(f"<b>Receipt Total: ${total:.2f}</b>")

    def _confirm(self):
        # Count how many promo lines will be skipped
        promo_count = sum(1 for _, _, qi, _, cb, _ in self._inputs
                         if cb.isChecked() and qi.value() > 0)

        msg = "Receive stock and update cost prices?"
        if promo_count:
            msg = (f"Receive stock?\n\n"
                   f"⚠  {promo_count} promo line(s) — stock will be received "
                   f"but cost price will NOT be updated for those items.")

        reply = QMessageBox.question(self, "Confirm Receipt", msg)
        if reply != QMessageBox.StandardButton.Yes:
            return

        all_received = True
        for line, pack_qty, qty_input, cost_input, promo_cb, lt_item in self._inputs:
            qty       = qty_input.value()
            item_cost = cost_input.value()
            is_promo  = promo_cb.isChecked()

            if qty > 0:
                cartons = max(1, math.ceil(qty / pack_qty))

                # Update po_line — received qty, actual_cost, and is_promo flag
                lines_model.receive(line['id'],
                                    line['received_qty'] + cartons,
                                    item_cost if item_cost > 0 else None)

                from database.connection import get_connection
                conn = get_connection()
                conn.execute(
                    "UPDATE po_lines SET unit_cost=?, is_promo=? WHERE id=?",
                    (item_cost, 1 if is_promo else 0, line['id'])
                )
                conn.commit()
                conn.close()

                # Update stock on hand (always — promo or not, stock still arrives)
                stock_model.adjust(
                    barcode=line['barcode'],
                    quantity=qty,
                    movement_type=MOVE_RECEIPT,
                    reference=f"PO-{self.po_id}",
                )

                # ── Cost price update — SKIPPED if promo ────────────────────
                if item_cost > 0 and not is_promo:
                    from database.connection import get_connection
                    conn = get_connection()
                    conn.execute(
                        "UPDATE products SET cost_price=?, updated_at=CURRENT_TIMESTAMP "
                        "WHERE barcode=?",
                        (item_cost, line['barcode'])
                    )
                    conn.commit()
                    conn.close()
                # ─────────────────────────────────────────────────────────────

            total_received_cartons = line['received_qty'] + (
                max(1, math.ceil(qty / pack_qty)) if qty > 0 else 0
            )
            if total_received_cartons < line['ordered_qty']:
                all_received = False

        status = PO_STATUS_RECEIVED if all_received else PO_STATUS_PARTIAL
        po_model.update_status(self.po_id, status)
        if self.on_save:
            self.on_save()
        QMessageBox.information(self, "Done", f"Stock received. PO status: {status}")
        self.close()
