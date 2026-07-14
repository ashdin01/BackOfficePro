from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QShortcut, QKeySequence
import controllers.purchase_order_controller as po_controller
import config.styles as styles
from utils.po_type_helpers import po_unit_mode
from views.purchase_orders.item_lookup_dialog import ItemLookupDialog


class AddLineDialog(QDialog):
    def __init__(self, po_id, supplier_id=None, po_type='PO', parent=None):
        super().__init__(parent)
        self.po_id = po_id
        self.supplier_id = supplier_id
        self._unit_mode = po_unit_mode(po_type)
        self.setWindowTitle("Add Line")
        self.setMinimumWidth(440)
        self._reorder_max = 0
        self._pack_qty = 1
        self._pack_unit = 'EA'
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        barcode_row = QHBoxLayout()
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")
        self.barcode.returnPressed.connect(self._on_barcode_enter)
        lookup_btn = QPushButton("🔍 F2")
        lookup_btn.setFixedWidth(70)
        lookup_btn.setFixedHeight(28)
        lookup_btn.setToolTip("Press F2 to open item lookup")
        lookup_btn.setAutoDefault(False)
        lookup_btn.setDefault(False)
        lookup_btn.clicked.connect(self._open_lookup)
        f2 = QShortcut(QKeySequence("F2"), self)
        f2.setContext(Qt.ShortcutContext.WindowShortcut)
        f2.activated.connect(self._open_lookup)
        barcode_row.addWidget(self.barcode)
        barcode_row.addWidget(lookup_btn)

        self.description = QLineEdit()
        self.description.setPlaceholderText("Auto-filled on barcode lookup")

        self.on_hand_label = QLabel("")
        self.on_hand_label.setStyleSheet("color: grey;")

        self.pack_label = QLabel("")
        self.pack_label.setStyleSheet("color: steelblue; font-style: italic;")

        self.sku_label = QLabel("")
        self.sku_label.setStyleSheet("color: steelblue; font-style: italic;")

        self.qty = QDoubleSpinBox()
        self.qty.setMinimum(1)
        self.qty.setMaximum(99999)
        self.qty.setDecimals(0)
        self.qty.setValue(1)
        self.qty.setSuffix(" unit(s)" if self._unit_mode else " carton(s)")
        self.qty.valueChanged.connect(self._update_unit_preview)
        self.qty.installEventFilter(self)

        self.unit_preview = QLabel("")
        self.unit_preview.setStyleSheet("color: #555; font-style: italic;")

        self.unit_cost = QDoubleSpinBox()
        self.unit_cost.setMaximum(99999)
        self.unit_cost.setPrefix("$")
        self.unit_cost.setDecimals(4)
        self.unit_cost.installEventFilter(self)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional")

        form.addRow("Barcode *",       barcode_row)
        form.addRow("Description",     self.description)
        form.addRow("Stock on Hand",   self.on_hand_label)
        form.addRow("Pack Size",       self.pack_label)
        form.addRow("Supplier SKU",    self.sku_label)
        form.addRow("Qty (Units) *" if self._unit_mode else "Qty (Cartons) *", self.qty)
        form.addRow("",                self.unit_preview)
        form.addRow("Unit Cost",       self.unit_cost)
        form.addRow("Notes",           self.notes)
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Add to PO")
        ok_btn.setFixedHeight(35)
        ok_btn.setDefault(False)
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(self._add)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        QShortcut(QKeySequence("Escape"), self, self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self, self._add)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if obj == self.qty:
                    self.unit_cost.setFocus()
                    self.unit_cost.selectAll()
                    return True
                elif obj == self.unit_cost:
                    self._add()
                    return True
        return super().eventFilter(obj, event)

    def _on_barcode_enter(self):
        self._lookup()
        self.qty.setFocus()
        self.qty.selectAll()

    def _open_lookup(self):
        dlg = ItemLookupDialog(parent=self, supplier_id=self.supplier_id)
        if dlg.exec() and dlg.selected:
            self.barcode.setText(dlg.selected["barcode"])
            self.unit_cost.setValue(dlg.selected["cost_price"])
            self._lookup()

    def _lookup(self):
        barcode = self.barcode.text().strip()
        if not barcode:
            return
        try:
            product = po_controller.lookup_product_for_po(barcode, self.po_id, self.supplier_id, self._unit_mode)
        except ValueError as e:
            code = str(e)
            if code.startswith("already_on_po:"):
                _, line_num, desc = code.split(":", 2)
                QMessageBox.warning(
                    self, "Item Already on PO",
                    f"This item is already on this PO at line {line_num}:\n\n{desc}\n\nEdit the existing line instead."
                )
            elif code.startswith("not_linked:"):
                po_name = code.split(":", 1)[1]
                QMessageBox.warning(
                    self, "Product Not Available",
                    f"This product is not linked to {po_name}.\n\nAdd {po_name} as a supplier for this product first."
                )
            self.barcode.clear()
            self.barcode.setFocus()
            return
        if product:
            self.description.setText(product['description'])
            self.unit_cost.setValue(product['cost_price'])
            self._pack_qty  = product['pack_qty']
            self._pack_unit = product['pack_unit']
            on_hand = product['on_hand']
            reorder = product['reorder_point']
            self.on_hand_label.setText(styles.html_colored_label(on_hand, reorder))
            self.pack_label.setText(f"{self._pack_qty} × {self._pack_unit} per carton")
            self.sku_label.setText(product.get('supplier_sku') or '—')
            self.qty.setValue(product['suggested_qty'])
            self._update_unit_preview()
        else:
            self.description.clear()
            self.pack_label.setText("")
            self.sku_label.setText("")
            self.on_hand_label.setText(styles.html_span("Product not found", styles.CLR_GP_BAD))

    def _update_unit_preview(self):
        qty = int(self.qty.value())
        if self._unit_mode:
            self.unit_preview.setText(
                f"= {qty} individual unit(s)  (pack size: {self._pack_qty} {self._pack_unit})"
            )
        else:
            total_units = qty * self._pack_qty
            self.unit_preview.setText(
                f"= {total_units} units  ({qty} × {self._pack_qty} {self._pack_unit})"
            )

    def _add(self):
        barcode     = self.barcode.text().strip()
        description = self.description.text().strip()
        if not barcode or not description:
            QMessageBox.warning(self, "Validation", "Barcode and Description are required.")
            return
        qty = int(self.qty.value())
        if self._unit_mode:
            po_controller.add_po_line(
                po_id=self.po_id,
                barcode=barcode,
                description=description,
                ordered_qty=qty,
                unit_cost=self.unit_cost.value(),
                notes='',
                pack_qty=self._pack_qty,
            )
        else:
            note = po_controller.carton_note(self._pack_qty, self._pack_unit, barcode)
            po_controller.add_po_line(
                po_id=self.po_id,
                barcode=barcode,
                description=description,
                ordered_qty=qty,
                unit_cost=self.unit_cost.value(),
                notes=note,
                pack_qty=self._pack_qty,
            )
        self.accept()
