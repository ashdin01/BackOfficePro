from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QDoubleSpinBox, QDialog, QFormLayout, QSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.product as product_model
import models.stock_on_hand as stock_model
from config.constants import PO_STATUS_SENT
from database.connection import get_connection


def get_recommendations(supplier_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.barcode, p.description, p.reorder_point, p.reorder_qty,
               p.cost_price, COALESCE(s.quantity, 0) as on_hand
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        WHERE p.supplier_id = ?
          AND p.active = 1
          AND COALESCE(s.quantity, 0) <= p.reorder_point
          AND p.reorder_qty > 0
        ORDER BY p.description
    """, (supplier_id,)).fetchall()
    conn.close()
    return rows


class PODetail(QWidget):
    def __init__(self, po_id, on_save=None):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self.setMinimumSize(950, 650)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header = QLabel()
        layout.addWidget(self.header)

        self.rec_banner = QLabel("")
        self.rec_banner.setStyleSheet("color: steelblue; padding: 4px;")
        layout.addWidget(self.rec_banner)

        # Editable table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "On Hand", "Reorder Pt", "Order Qty", "Unit Cost $"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Allow editing on Qty and Cost columns only — enforced via itemChanged
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.total_label = QLabel()
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)

        btns = QHBoxLayout()

        btn_add = QPushButton("&Add Line")
        btn_add.setFixedHeight(35)
        btn_add.setToolTip("Add a line [A]")
        btn_add.clicked.connect(self._add_line)

        btn_del = QPushButton("&Remove Line")
        btn_del.setFixedHeight(35)
        btn_del.setToolTip("Remove selected line [R]")
        btn_del.clicked.connect(self._remove_line)

        btn_reload = QPushButton("&Reload Recommendations")
        btn_reload.setFixedHeight(35)
        btn_reload.setToolTip("Reload recommendations [R... hold]")
        btn_reload.clicked.connect(self._reload_recommendations)

        btn_send = QPushButton("&Mark as Sent ✓")
        btn_send.setFixedHeight(35)
        btn_send.setToolTip("Mark PO as sent [M]")
        btn_send.clicked.connect(self._mark_sent)

        btn_cancel = QPushButton("&Cancel PO")
        btn_cancel.setFixedHeight(35)
        btn_cancel.setToolTip("Cancel this PO [C]")
        btn_cancel.clicked.connect(self._cancel_po)

        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addWidget(btn_reload)
        btns.addStretch()
        btns.addWidget(btn_send)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

        QShortcut(QKeySequence("A"), self, self._add_line)
        QShortcut(QKeySequence("M"), self, self._mark_sent)
        QShortcut(QKeySequence("C"), self, self._cancel_po)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        po = po_model.get_by_id(self.po_id)
        self._po = po
        self.setWindowTitle(f"PO: {po['po_number']}")
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — "
            f"Status: <b>{po['status']}</b> — "
            f"Delivery: {po['delivery_date'] or 'TBC'}"
        )
        lines = lines_model.get_by_po(self.po_id)

        # Auto-load recommendations if no lines yet
        if len(lines) == 0:
            self._auto_load_recommendations()
            lines = lines_model.get_by_po(self.po_id)

        self._populate_table(lines)

    def _auto_load_recommendations(self):
        recs = get_recommendations(self._po['supplier_id'])
        if not recs:
            self.rec_banner.setText("✓ All stock levels are above reorder points for this supplier.")
            return
        for r in recs:
            lines_model.add(
                po_id=self.po_id,
                barcode=r['barcode'],
                description=r['description'],
                ordered_qty=int(r['reorder_qty']),
                unit_cost=r['cost_price'],
            )
        self.rec_banner.setText(
            f"💡 {len(recs)} line(s) auto-loaded from reorder points. "
            f"Edit quantities and costs directly in the table."
        )

    def _reload_recommendations(self):
        recs = get_recommendations(self._po['supplier_id'])
        if not recs:
            QMessageBox.information(self, "Recommendations",
                "All products for this supplier are above reorder points.")
            return
        existing = {l['barcode'] for l in lines_model.get_by_po(self.po_id)}
        new_recs = [r for r in recs if r['barcode'] not in existing]
        if not new_recs:
            QMessageBox.information(self, "Recommendations",
                "All recommended products are already on this PO.")
            return
        for r in new_recs:
            lines_model.add(
                po_id=self.po_id,
                barcode=r['barcode'],
                description=r['description'],
                ordered_qty=int(r['reorder_qty']),
                unit_cost=r['cost_price'],
            )
        self.rec_banner.setText(f"✓ {len(new_recs)} additional line(s) added.")
        lines = lines_model.get_by_po(self.po_id)
        self._populate_table(lines)
        if self.on_save:
            self.on_save()

    def _populate_table(self, lines):
        # Block signals while populating to avoid itemChanged firing
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self._line_ids = []
        total = 0

        for line in lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._line_ids.append(line['id'])

            # Barcode — read only
            barcode_item = QTableWidgetItem(line['barcode'])
            barcode_item.setFlags(barcode_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, barcode_item)

            # Description — read only
            desc_item = QTableWidgetItem(line['description'])
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, desc_item)

            # On Hand — read only
            soh = stock_model.get_by_barcode(line['barcode'])
            on_hand = int(soh['quantity']) if soh else 0
            soh_item = QTableWidgetItem(str(on_hand))
            soh_item.setFlags(soh_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            soh_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 2, soh_item)

            # Reorder Point — read only
            product = product_model.get_by_barcode(line['barcode'])
            reorder_pt = int(product['reorder_point']) if product else 0
            rp_item = QTableWidgetItem(str(reorder_pt))
            rp_item.setFlags(rp_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            rp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, rp_item)

            # Qty — EDITABLE
            qty_item = QTableWidgetItem(str(int(line['ordered_qty'])))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, qty_item)

            # Unit Cost — EDITABLE
            cost_item = QTableWidgetItem(f"{line['unit_cost']:.2f}")
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 5, cost_item)

            total += line['ordered_qty'] * line['unit_cost']

        self.table.blockSignals(False)
        self._update_total()

    def _on_item_changed(self, item):
        row = item.row()
        col = item.column()
        if col not in (4, 5):  # Only qty and cost are editable
            return
        if row >= len(self._line_ids):
            return

        line_id = self._line_ids[row]
        try:
            if col == 4:  # Qty
                qty = int(float(item.text()))
                if qty < 1:
                    qty = 1
                # MOQ check
                barcode = self.table.item(row, 0).text()
                product = product_model.get_by_barcode(barcode)
                if product and product['reorder_qty'] > 0:
                    moq = int(product['reorder_qty'])
                    if qty % moq != 0:
                        self.rec_banner.setText(
                            f"⚠ MOQ warning: {self.table.item(row,1).text()} — "
                            f"order in multiples of {moq}"
                        )
                    else:
                        self.rec_banner.setText("")
                lines_model.update(line_id, ordered_qty=qty)
            elif col == 5:  # Cost
                cost = float(item.text().replace("$", "").strip())
                if cost < 0:
                    cost = 0
                lines_model.update(line_id, unit_cost=cost)
        except (ValueError, TypeError):
            pass  # Ignore bad input

        self._update_total()

    def _update_total(self):
        total = 0
        for r in range(self.table.rowCount()):
            try:
                qty = float(self.table.item(r, 4).text())
                cost = float(self.table.item(r, 5).text().replace("$", "").strip())
                total += qty * cost
            except (ValueError, AttributeError):
                pass
        self.total_label.setText(f"<b>Order Total: ${total:.2f}</b>")

    def _add_line(self):
        dlg = AddLineDialog(self.po_id, parent=self)
        if dlg.exec():
            lines = lines_model.get_by_po(self.po_id)
            self._populate_table(lines)
            if self.on_save:
                self.on_save()

    def _remove_line(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Remove Line", "Select a line first.")
            return
        if row >= len(self._line_ids):
            return
        line_id = self._line_ids[row]
        reply = QMessageBox.question(self, "Confirm", "Remove this line?")
        if reply == QMessageBox.StandardButton.Yes:
            lines_model.delete(line_id)
            lines = lines_model.get_by_po(self.po_id)
            self._populate_table(lines)

    def _mark_sent(self):
        lines = lines_model.get_by_po(self.po_id)
        if not lines:
            QMessageBox.warning(self, "Cannot Send", "Add at least one line before sending.")
            return
        reply = QMessageBox.question(self, "Confirm", "Mark this PO as Sent?")
        if reply == QMessageBox.StandardButton.Yes:
            po_model.update_status(self.po_id, PO_STATUS_SENT)
            self._load()
            if self.on_save:
                self.on_save()

    def _cancel_po(self):
        reply = QMessageBox.question(
            self, "Confirm", "Cancel this PO? This cannot be undone.")
        if reply == QMessageBox.StandardButton.Yes:
            po_model.cancel(self.po_id)
            if self.on_save:
                self.on_save()
            self.close()


class AddLineDialog(QDialog):
    def __init__(self, po_id, parent=None):
        super().__init__(parent)
        self.po_id = po_id
        self.setWindowTitle("Add Line")
        self.setMinimumWidth(420)
        self._reorder_qty = 0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")
        self.barcode.editingFinished.connect(self._lookup)

        self.description = QLineEdit()
        self.description.setPlaceholderText("Auto-filled on barcode lookup")

        self.on_hand_label = QLabel("")
        self.on_hand_label.setStyleSheet("color: grey;")

        self.qty = QDoubleSpinBox()
        self.qty.setMinimum(1)
        self.qty.setMaximum(99999)
        self.qty.setDecimals(0)
        self.qty.setValue(1)
        self.qty.valueChanged.connect(self._check_moq)

        self.moq_label = QLabel("")
        self.moq_label.setStyleSheet("color: orange;")

        self.unit_cost = QDoubleSpinBox()
        self.unit_cost.setMaximum(99999)
        self.unit_cost.setPrefix("$")
        self.unit_cost.setDecimals(2)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional")

        form.addRow("Barcode *", self.barcode)
        form.addRow("Description", self.description)
        form.addRow("Stock on Hand", self.on_hand_label)
        form.addRow("Qty *", self.qty)
        form.addRow("", self.moq_label)
        form.addRow("Unit Cost", self.unit_cost)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Add to PO")
        ok_btn.setFixedHeight(35)
        ok_btn.clicked.connect(self._add)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self, self._add)

    def _lookup(self):
        barcode = self.barcode.text().strip()
        if not barcode:
            return
        product = product_model.get_by_barcode(barcode)
        if product:
            self.description.setText(product['description'])
            self.unit_cost.setValue(product['cost_price'])
            self._reorder_qty = int(product['reorder_qty']) if product['reorder_qty'] else 0
            soh = stock_model.get_by_barcode(barcode)
            on_hand = int(soh['quantity']) if soh else 0
            reorder = int(product['reorder_point'])
            color = "red" if on_hand <= reorder else "green"
            self.on_hand_label.setText(
                f"<span style='color:{color}'>{on_hand}</span> "
                f"(reorder at {reorder}, suggest {self._reorder_qty})"
            )
            self.qty.setValue(self._reorder_qty if self._reorder_qty > 0 else 1)
            self._check_moq()
        else:
            self.description.clear()
            self.on_hand_label.setText("<span style='color:red'>Product not found</span>")

    def _check_moq(self):
        if self._reorder_qty > 0:
            qty = int(self.qty.value())
            if qty % self._reorder_qty != 0:
                self.moq_label.setText(
                    f"⚠ MOQ is {self._reorder_qty} — order in multiples of {self._reorder_qty}"
                )
            else:
                self.moq_label.setText("")

    def _add(self):
        barcode = self.barcode.text().strip()
        description = self.description.text().strip()
        if not barcode or not description:
            QMessageBox.warning(self, "Validation", "Barcode and Description are required.")
            return
        qty = int(self.qty.value())
        if self._reorder_qty > 0 and qty % self._reorder_qty != 0:
            reply = QMessageBox.warning(
                self, "MOQ Warning",
                f"Minimum order quantity is {self._reorder_qty}.\n"
                f"You entered {qty}. Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        lines_model.add(
            po_id=self.po_id,
            barcode=barcode,
            description=description,
            ordered_qty=qty,
            unit_cost=self.unit_cost.value(),
            notes=self.notes.text(),
        )
        self.accept()
