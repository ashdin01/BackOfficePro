from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QSpinBox,
    QComboBox, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut, QKeySequence
import config.styles as styles

PACK_UNIT_OPTIONS = ['ea', 'kg', 'l', 'pk', 'ctn', 'g', 'ml']


class SupplierLinksDialog(QDialog):
    """Manage the suppliers linked to a product — SKU, pack size, default
    supplier, and read-only last cost per supplier.

    Mutates `product_suppliers` in place rather than copying it in/out, so
    the caller's own reference (which it also hands to the save controller)
    stays in sync with whatever was added, removed, or edited here.
    """

    def __init__(self, product_suppliers, all_suppliers, read_only=False, parent=None):
        super().__init__(parent)
        self._product_suppliers = product_suppliers
        self._suppliers = all_suppliers
        self._read_only = read_only
        self.setWindowTitle("Manage Suppliers  [View Only]" if read_only else "Manage Suppliers")
        self.setMinimumWidth(820)
        self.setMinimumHeight(320)
        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        note_text = (
            "Suppliers linked to this product, their SKU, pack size, and last cost. "
            "Contact a manager to make changes."
            if self._read_only else
            "The Default supplier determines which purchase orders this product appears in. "
            "Set the Supplier SKU and carton pack size per supplier."
        )
        note = QLabel(note_text)
        note.setStyleSheet(styles.STYLE_LABEL_MUTED)
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Supplier", "Supplier SKU", "Pack Qty", "Unit",
             "Cost Price (ex GST)", "Default", ""]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 75)
        self.table.setColumnWidth(3, 65)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 110)
        self.table.setColumnWidth(6, 50)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(120)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        if not self._read_only:
            btn_add = QPushButton("+ Add Supplier")
            btn_add.setFixedHeight(30)
            btn_add.clicked.connect(self._add_supplier_popup)
            btn_row.addWidget(btn_add)
        btn_row.addStretch()
        btn_done = QPushButton("Close" if self._read_only else "Done")
        btn_done.setFixedHeight(32)
        btn_done.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
            "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
        )
        btn_done.clicked.connect(self.accept)
        btn_row.addWidget(btn_done)
        layout.addLayout(btn_row)

    @staticmethod
    def _ro_cell(text):
        """Plain, non-editable, centred table cell — used in STAFF's
        view-only mode, in place of the normally-editable widgets."""
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _refresh_table(self):
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self._product_suppliers))
        for r, entry in enumerate(self._product_suppliers):
            self.table.setItem(r, 0, QTableWidgetItem(entry['supplier_name']))

            if self._read_only:
                # Col 1 — Supplier SKU (plain text)
                self.table.setItem(r, 1, self._ro_cell(entry.get('supplier_sku') or '—'))

                # Col 2 — Pack Qty (plain text)
                self.table.setItem(r, 2, self._ro_cell(str(entry.get('pack_qty') or 1)))

                # Col 3 — Pack Unit (plain text)
                self.table.setItem(r, 3, self._ro_cell(entry.get('pack_unit') or 'ea'))
            else:
                # Col 1 — Supplier SKU (inline QLineEdit)
                sku_edit = QLineEdit(entry.get('supplier_sku') or '')
                sku_edit.setPlaceholderText("e.g. BIP-240")
                sku_edit.textChanged.connect(
                    lambda text, i=r: self._product_suppliers[i].__setitem__('supplier_sku', text.strip())
                )
                self.table.setCellWidget(r, 1, sku_edit)

                # Col 2 — Pack Qty (inline QSpinBox)
                qty_spin = QSpinBox()
                qty_spin.setMinimum(1)
                qty_spin.setMaximum(9999)
                qty_spin.setValue(entry.get('pack_qty') or 1)
                qty_spin.valueChanged.connect(
                    lambda val, i=r: self._product_suppliers[i].__setitem__('pack_qty', val)
                )
                self.table.setCellWidget(r, 2, qty_spin)

                # Col 3 — Pack Unit (inline QComboBox)
                unit_cb = QComboBox()
                unit_cb.addItems(PACK_UNIT_OPTIONS)
                # Match case-insensitively: existing rows may still have an
                # upper-case value stored from before the list was lower-cased.
                pack_unit_val = (entry.get('pack_unit') or 'ea').lower()
                unit_cb.setCurrentText(pack_unit_val if pack_unit_val in PACK_UNIT_OPTIONS else 'ea')
                unit_cb.currentTextChanged.connect(
                    lambda text, i=r: self._product_suppliers[i].__setitem__('pack_unit', text)
                )
                self.table.setCellWidget(r, 3, unit_cb)

            # Col 4 — Cost Price ex GST: read-only, most recent cost on file
            # for this supplier from PO history. Not editable here — blank
            # when this supplier has never had a PO line for the product.
            last_cost = entry.get('last_cost')
            cost_text = f"${last_cost:.4f}" if last_cost is not None else "—"
            self.table.setItem(r, 4, self._ro_cell(cost_text))

            # Col 5 — Default
            if self._read_only:
                self.table.setItem(
                    r, 5, self._ro_cell("★ Default" if entry['is_default'] else "")
                )
            elif entry['is_default']:
                btn_def = QPushButton("★ Default")
                btn_def.setEnabled(False)
                btn_def.setFixedHeight(26)
                btn_def.setStyleSheet(
                    f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
                    "border-radius: 3px; font-weight: bold; }"
                )
                self.table.setCellWidget(r, 5, btn_def)
            else:
                btn_def = QPushButton("Set Default")
                btn_def.setFixedHeight(26)
                btn_def.clicked.connect(lambda _, i=r: self._set_default_supplier(i))
                self.table.setCellWidget(r, 5, btn_def)

            # Col 6 — Remove (hidden entirely in view-only mode)
            if not self._read_only:
                btn_rem = QPushButton("✕")
                btn_rem.setFixedHeight(26)
                btn_rem.setStyleSheet(f"color: {styles.CLR_DANGER_ALT}; font-weight: bold;")
                btn_rem.clicked.connect(lambda _, i=r: self._remove_supplier(i))
                self.table.setCellWidget(r, 6, btn_rem)

        self.table.setUpdatesEnabled(True)

    def _add_supplier_popup(self):
        existing_ids = {e['supplier_id'] for e in self._product_suppliers}
        available = [s for s in self._suppliers if s['id'] not in existing_ids]
        if not available:
            QMessageBox.information(self, "Add Supplier", "All suppliers are already linked to this product.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Add Supplier")
        dlg.setMinimumWidth(380)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        sup_combo = QComboBox()
        for s in available:
            sup_combo.addItem(s['name'], s['id'])
        form.addRow("Supplier", sup_combo)

        sku_input = QLineEdit()
        sku_input.setPlaceholderText("e.g. BIP-240")
        form.addRow("Supplier SKU", sku_input)

        pack_layout = QHBoxLayout()
        qty_spin = QSpinBox()
        qty_spin.setMinimum(1)
        qty_spin.setMaximum(9999)
        qty_spin.setValue(1)
        qty_spin.setFixedWidth(80)
        unit_cb = QComboBox()
        unit_cb.addItems(PACK_UNIT_OPTIONS)
        unit_cb.setFixedWidth(80)
        pack_layout.addWidget(qty_spin)
        pack_layout.addWidget(unit_cb)
        pack_layout.addStretch()
        form.addRow("Pack Size", pack_layout)

        layout.addLayout(form)
        layout.addSpacing(4)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("Add  [Ctrl+S]")
        ok_btn.setFixedHeight(32)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
            "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
        )
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(32)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        def confirm():
            sup_id   = sup_combo.currentData()
            sup_name = sup_combo.currentText()
            self._product_suppliers.append({
                'supplier_id':   sup_id,
                'supplier_name': sup_name,
                'is_default':    len(self._product_suppliers) == 0,
                'supplier_sku':  sku_input.text().strip(),
                'pack_qty':      qty_spin.value(),
                'pack_unit':     unit_cb.currentText(),
            })
            self._refresh_table()
            dlg.accept()

        ok_btn.clicked.connect(confirm)
        cancel_btn.clicked.connect(dlg.reject)
        QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
        QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
        sku_input.setFocus()
        dlg.exec()

    def _remove_supplier(self, idx):
        was_default = self._product_suppliers[idx]['is_default']
        del self._product_suppliers[idx]
        if was_default and self._product_suppliers:
            self._product_suppliers[0]['is_default'] = True
        self._refresh_table()

    def _set_default_supplier(self, idx):
        for i, entry in enumerate(self._product_suppliers):
            entry['is_default'] = (i == idx)
        self._refresh_table()
