from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox,
    QDoubleSpinBox, QLabel, QDialog, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QCheckBox, QSpinBox
)
from PyQt6.QtCore import Qt
from utils.keyboard_mixin import KeyboardMixin
import models.product as product_model
import models.department as dept_model
import models.supplier as supplier_model
import models.barcode_alias as alias_model
import models.group as group_model


class ProductEdit(KeyboardMixin, QWidget):
    def __init__(self, barcode, on_save=None):
        super().__init__()
        self.setWindowTitle("Product Detail")
        self.setMinimumWidth(560)
        self.setMinimumHeight(750)
        self.barcode = barcode
        self.on_save = on_save
        self._depts = dept_model.get_all()
        self._suppliers = supplier_model.get_all()
        self._groups = group_model.get_all(active_only=False)
        self.product = product_model.get_by_barcode(barcode)
        self._init_values()
        self._build_ui()
        self.setup_keyboard()

    def _init_values(self):
        p = self.product
        self._description   = p['description']
        self._brand         = p['brand'] or ''
        self._sku           = p['sku'] or ''
        self._supplier_sku  = p['supplier_sku'] or ''
        self._pack_qty      = int(p['pack_qty']) if 'pack_qty' in p.keys() and p['pack_qty'] else 1
        self._pack_unit     = p['pack_unit'] if 'pack_unit' in p.keys() and p['pack_unit'] else 'EA'
        self._group_id      = p['group_id'] if 'group_id' in p.keys() else None
        self._dept_id       = p['department_id']
        self._supplier_id   = p['supplier_id']
        self._unit          = p['unit'] or 'EA'
        self._sell_price    = p['sell_price']
        self._cost_price    = p['cost_price']
        self._tax_rate      = p['tax_rate']
        self._reorder_point = p['reorder_point']
        self._reorder_max   = p['reorder_max'] if 'reorder_max' in p.keys() and p['reorder_max'] else 0
        self._variable_wt   = bool(p['variable_weight'])
        self._in_stocktake  = bool(p['expected'])
        self._active        = bool(p['active'])

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        def ro_row(value, on_edit):
            row = QHBoxLayout()
            lbl = QLabel(str(value))
            lbl.setMinimumWidth(300)
            btn = QPushButton("✎")
            btn.setFixedSize(28, 28)
            btn.clicked.connect(on_edit)
            row.addWidget(lbl)
            row.addWidget(btn)
            row.addStretch()
            return row, lbl

        # ── Field order per spec ──────────────────────────────────────
        form.addRow("Barcode", QLabel(self.product['barcode']))

        r, self.lbl_desc = ro_row(self._description, self._edit_description)
        form.addRow("Description", r)

        r, self.lbl_brand = ro_row(self._brand or "—", self._edit_brand)
        form.addRow("Brand", r)

        r, self.lbl_sku = ro_row(self._sku or "—", self._edit_sku)
        form.addRow("SKU", r)

        r, self.lbl_supplier = ro_row(self._supplier_name(), self._edit_supplier)
        form.addRow("Supplier", r)

        # Supplier SKU + pack size on one row
        r, self.lbl_supplier_sku = ro_row(self._supplier_sku_display(), self._edit_supplier_sku)
        form.addRow("Supplier SKU", r)

        r, self.lbl_dept = ro_row(self._dept_name(), self._edit_dept)
        form.addRow("Department", r)

        r, self.lbl_group = ro_row(self._group_name(), self._edit_group)
        form.addRow("Group", r)

        r, self.lbl_unit = ro_row(self._unit, self._edit_unit)
        form.addRow("Unit", r)

        r, self.lbl_cost = ro_row(f"${self._cost_price:.4f}", self._edit_cost)
        form.addRow("Cost Price", r)

        r, self.lbl_sell = ro_row(f"${self._sell_price:.2f}", self._edit_sell)
        form.addRow("Sell Price", r)

        self.lbl_gp = QLabel()
        self.lbl_gp.setTextFormat(Qt.TextFormat.RichText)
        self._refresh_gp()
        form.addRow("Gross Profit", self.lbl_gp)

        r, self.lbl_tax = ro_row(self._tax_label(), self._edit_tax)
        form.addRow("Tax Rate", r)

        r, self.lbl_reorder_pt = ro_row(int(self._reorder_point), self._edit_reorder_point)
        form.addRow("Reorder Point", r)


        r, self.lbl_reorder_max = ro_row(int(self._reorder_max), self._edit_reorder_max)
        form.addRow("Reorder Max", r)

        r, self.lbl_vw = ro_row("Yes" if self._variable_wt else "No", self._edit_variable_wt)
        form.addRow("Variable Weight", r)

        r, self.lbl_stocktake = ro_row("Yes" if self._in_stocktake else "No", self._edit_stocktake)
        form.addRow("Include in Stocktake", r)

        r, self.lbl_active = ro_row("Yes" if self._active else "No", self._edit_active)
        form.addRow("Active", r)

        layout.addLayout(form)

        # Alternate barcodes
        # ── Movement History button ───────────────────────────────
        hist_row = QHBoxLayout()
        btn_history = QPushButton("📋 View Movement History")
        btn_history.setFixedHeight(30)
        btn_history.clicked.connect(self._view_history)
        hist_row.addWidget(btn_history)
        hist_row.addStretch()
        layout.addLayout(hist_row)

        alias_group = QGroupBox("Alternate Barcodes")
        alias_layout = QVBoxLayout(alias_group)
        self.alias_table = QTableWidget()
        self.alias_table.setColumnCount(3)
        self.alias_table.setHorizontalHeaderLabels(["Barcode", "Note", "Added"])
        self.alias_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.alias_table.setMaximumHeight(140)
        self.alias_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alias_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        alias_layout.addWidget(self.alias_table)
        alias_btns = QHBoxLayout()
        btn_add_alias = QPushButton("+ Add Barcode")
        btn_add_alias.clicked.connect(self._add_alias)
        btn_del_alias = QPushButton("Remove")
        btn_del_alias.clicked.connect(self._remove_alias)
        alias_btns.addWidget(btn_add_alias)
        alias_btns.addWidget(btn_del_alias)
        alias_btns.addStretch()
        alias_layout.addLayout(alias_btns)
        layout.addWidget(alias_group)
        self._load_aliases()

        layout.addSpacing(8)
        btns = QHBoxLayout()
        save_btn = QPushButton("Save  [Ctrl+S]")
        save_btn.setFixedHeight(35)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    # ── Supplier SKU display ──────────────────────────────────────────

    def _supplier_sku_display(self):
        base = self._supplier_sku or "—"
        if self._pack_qty and self._pack_qty > 1:
            return f"{base}  ({self._pack_qty} × {self._pack_unit} per carton)"
        return base

    # ── Edit popup helpers ────────────────────────────────────────────

    def _edit_description(self):
        val = _text_popup("Edit Description", "Description", self._description, self)
        if val is not None:
            self._description = val
            self.lbl_desc.setText(val)

    def _edit_brand(self):
        val = _text_popup_optional("Edit Brand", "Brand", self._brand, self)
        if val is not None:
            self._brand = val
            self.lbl_brand.setText(val or "—")

    def _edit_sku(self):
        val = _text_popup_optional("Edit SKU", "SKU", self._sku, self)
        if val is not None:
            self._sku = val
            self.lbl_sku.setText(val or "—")

    def _edit_supplier_sku(self):
        result = _supplier_sku_popup(self._supplier_sku, self._pack_qty, self._pack_unit, self)
        if result is not None:
            self._supplier_sku, self._pack_qty, self._pack_unit = result
            self.lbl_supplier_sku.setText(self._supplier_sku_display())

    def _group_name(self):
        if not self._group_id:
            return "— No Group —"
        for g in self._groups:
            if g['id'] == self._group_id:
                return g['name']
        return "— No Group —"

    def _edit_group(self):
        dept_groups = [g for g in self._groups if g['department_id'] == self._dept_id]
        names = ["— No Group —"] + [g['name'] for g in dept_groups]
        ids   = [None]           + [g['id']   for g in dept_groups]
        current_name = self._group_name()
        val = _choice_popup("Edit Group", "Group", names, current_name, self)
        if val is not None:
            self._group_id = ids[names.index(val)]
            self.lbl_group.setText(val)

    def _edit_dept(self):
        names = [d['name'] for d in self._depts]
        ids   = [d['id']   for d in self._depts]
        current = names[ids.index(self._dept_id)] if self._dept_id in ids else names[0]
        val = _choice_popup("Edit Department", "Department", names, current, self)
        if val is not None:
            self._dept_id = ids[names.index(val)]
            self.lbl_dept.setText(val)

    def _edit_supplier(self):
        names = ["-- None --"] + [s['name'] for s in self._suppliers]
        ids   = [None]         + [s['id']   for s in self._suppliers]
        current_idx = ids.index(self._supplier_id) if self._supplier_id in ids else 0
        val = _choice_popup("Edit Supplier", "Supplier", names, names[current_idx], self)
        if val is not None:
            self._supplier_id = ids[names.index(val)]
            self.lbl_supplier.setText(val)

    def _edit_unit(self):
        units = ['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML']
        val = _choice_popup("Edit Unit", "Unit", units, self._unit, self)
        if val is not None:
            self._unit = val
            self.lbl_unit.setText(val)

    def _edit_sell(self):
        val = _price_popup("Edit Sell Price", "Sell Price", self._sell_price, self)
        if val is not None:
            self._sell_price = val
            self.lbl_sell.setText(f"${val:.2f}")
            self._refresh_gp()

    def _edit_cost(self):
        val = _price_popup("Edit Cost Price", "Cost Price", self._cost_price, self)
        if val is not None:
            self._cost_price = val
            self.lbl_cost.setText(f"${val:.4f}")
            self._refresh_gp()

    def _edit_tax(self):
        options = ["GST Free (0%)", "GST (10%)"]
        val = _choice_popup("Edit Tax Rate", "Tax Rate", options, self._tax_label(), self)
        if val is not None:
            self._tax_rate = 10.0 if "10%" in val else 0.0
            self.lbl_tax.setText(val)

    def _edit_reorder_point(self):
        val = _number_popup("Edit Reorder Point", "Reorder Point", self._reorder_point, self)
        if val is not None:
            self._reorder_point = val
            self.lbl_reorder_pt.setText(str(int(val)))


    def _edit_reorder_max(self):
        val = _number_popup("Edit Reorder Max", "Reorder Max (0 = use Reorder Qty)", self._reorder_max, self)
        if val is not None:
            self._reorder_max = val
            self.lbl_reorder_max.setText(str(int(val)))

    def _edit_variable_wt(self):
        val = _choice_popup("Variable Weight", "Variable weight item?", ["No", "Yes"],
                            "Yes" if self._variable_wt else "No", self)
        if val is not None:
            self._variable_wt = (val == "Yes")
            self.lbl_vw.setText(val)

    def _edit_stocktake(self):
        val = _choice_popup("Include in Stocktake", "Include in stocktake?", ["Yes", "No"],
                            "Yes" if self._in_stocktake else "No", self)
        if val is not None:
            self._in_stocktake = (val == "Yes")
            self.lbl_stocktake.setText(val)

    def _edit_active(self):
        val = _choice_popup("Active Status", "Active?", ["Yes", "No"],
                            "Yes" if self._active else "No", self)
        if val is not None:
            self._active = (val == "Yes")
            self.lbl_active.setText(val)

    # ── Helpers ───────────────────────────────────────────────────────

    def _dept_name(self):
        for d in self._depts:
            if d['id'] == self._dept_id:
                return d['name']
        return "Unknown"

    def _supplier_name(self):
        for s in self._suppliers:
            if s['id'] == self._supplier_id:
                return s['name']
        return "-- None --"

    def _tax_label(self):
        return "GST (10%)" if self._tax_rate == 10.0 else "GST Free (0%)"

    def _refresh_gp(self):
        sell, cost = self._sell_price, self._cost_price
        if sell > 0:
            gp = (1 - cost / sell) * 100
            color = "green" if gp >= 30 else "orange" if gp >= 15 else "red"
            self.lbl_gp.setText(f"<b style='color:{color}'>{gp:.1f}%</b>")
        else:
            self.lbl_gp.setText("<b style='color:grey'>--</b>")

    def _load_aliases(self):
        aliases = alias_model.get_aliases(self.barcode)
        self.alias_table.setRowCount(0)
        for a in aliases:
            r = self.alias_table.rowCount()
            self.alias_table.insertRow(r)
            self.alias_table.setItem(r, 0, QTableWidgetItem(a['alias_barcode']))
            self.alias_table.setItem(r, 1, QTableWidgetItem(a['description'] or ''))
            self.alias_table.setItem(r, 2, QTableWidgetItem(str(a['created_at'])[:10]))
            self.alias_table.item(r, 0).setData(Qt.ItemDataRole.UserRole, a['id'])

    def _add_alias(self):
        dlg = AddAliasDialog(master_barcode=self.barcode, parent=self)
        if dlg.exec():
            self._load_aliases()

    def _remove_alias(self):
        row = self.alias_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Remove", "Select a barcode first.")
            return
        alias_id = self.alias_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, "Confirm", "Remove this alternate barcode?") == QMessageBox.StandardButton.Yes:
            alias_model.delete(alias_id)
            self._load_aliases()

    def _view_history(self):
        """Open movement history popup for this product."""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
            QTableWidgetItem, QHeaderView, QLabel, QComboBox, QPushButton
        )
        from PyQt6.QtGui import QColor
        from database.connection import get_connection

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Movement History — {self.product['barcode']}")
        dlg.setMinimumSize(820, 500)
        layout = QVBoxLayout(dlg)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Type:"))
        type_cb = QComboBox()
        type_cb.addItems(["ALL", "RECEIPT", "SALE", "ADJUSTMENT", "ADJUSTMENT_IN",
                          "ADJUSTMENT_OUT", "WASTAGE", "SHRINKAGE", "RETURN", "STOCKTAKE"])
        filter_row.addWidget(type_cb)
        filter_row.addStretch()
        status_lbl = QLabel()
        filter_row.addWidget(status_lbl)
        layout.addLayout(filter_row)

        # Table
        tbl = QTableWidget()
        tbl.setColumnCount(6)
        tbl.setHorizontalHeaderLabels(["Date/Time", "Type", "Qty", "Balance", "Reference", "Notes"])
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        tbl.setColumnWidth(0, 135)
        tbl.setColumnWidth(1, 110)
        tbl.setColumnWidth(2, 60)
        tbl.setColumnWidth(3, 70)
        tbl.setColumnWidth(4, 110)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.setSortingEnabled(False)
        layout.addWidget(tbl)

        def load(move_type=None):
            conn = get_connection()
            sql = """
                SELECT movement_type, quantity, reference, notes, created_at
                FROM stock_movements
                WHERE barcode = ?
            """
            params = [self.barcode]
            if move_type and move_type != "ALL":
                sql += " AND movement_type = ?"
                params.append(move_type)
            sql += " ORDER BY created_at ASC"
            rows = conn.execute(sql, params).fetchall()
            conn.close()

            tbl.setRowCount(0)
            balance = 0.0
            display_rows = []
            for row in rows:
                balance += row["quantity"]
                display_rows.append((row, balance))

            # Show newest first
            for row, bal in reversed(display_rows):
                r = tbl.rowCount()
                tbl.insertRow(r)
                tbl.setItem(r, 0, QTableWidgetItem(str(row["created_at"])[:16]))

                type_item = QTableWidgetItem(row["movement_type"])
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty = row["quantity"]
                if row["movement_type"] in ("RECEIPT", "ADJUSTMENT_IN", "RETURN"):
                    type_item.setForeground(QColor("#4CAF50"))
                elif row["movement_type"] in ("SALE", "WASTAGE", "ADJUSTMENT_OUT", "SHRINKAGE"):
                    type_item.setForeground(QColor("#f85149"))
                else:
                    type_item.setForeground(QColor("steelblue"))
                tbl.setItem(r, 1, type_item)

                qty_item = QTableWidgetItem(f"{'+' if qty > 0 else ''}{qty:.0f}")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty_item.setForeground(QColor("#4CAF50") if qty > 0 else QColor("#f85149"))
                tbl.setItem(r, 2, qty_item)

                bal_item = QTableWidgetItem(f"{bal:.0f}")
                bal_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                bal_item.setForeground(
                    QColor("#4CAF50") if bal > 0 else
                    QColor("#FF9800") if bal == 0 else
                    QColor("#f85149")
                )
                tbl.setItem(r, 3, bal_item)
                tbl.setItem(r, 4, QTableWidgetItem(row["reference"] or ""))
                tbl.setItem(r, 5, QTableWidgetItem(row["notes"] or ""))

            status_lbl.setText(f"{tbl.rowCount()} movements")

        type_cb.currentTextChanged.connect(load)
        load()

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close  [Esc]")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), dlg, dlg.accept)
        dlg.exec()

    def _save(self):
        if not self._description.strip():
            QMessageBox.warning(self, "Validation", "Description is required.")
            return
        try:
            product_model.update(
                barcode=self.barcode,
                description=self._description,
                brand=self._brand,
                sku=self._sku,
                supplier_sku=self._supplier_sku,
                pack_qty=self._pack_qty,
                pack_unit=self._pack_unit,
                group_id=self._group_id,
                department_id=self._dept_id,
                supplier_id=self._supplier_id,
                unit=self._unit,
                sell_price=self._sell_price,
                cost_price=self._cost_price,
                tax_rate=self._tax_rate,
                reorder_point=self._reorder_point,
                reorder_max=self._reorder_max,
                variable_weight=int(self._variable_wt),
                expected=int(self._in_stocktake),
                active=int(self._active),
            )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


# ── Supplier SKU popup with pack size ─────────────────────────────────

def _supplier_sku_popup(current_sku, current_pack_qty, current_pack_unit, parent=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle("Edit Supplier SKU")
    dlg.setMinimumWidth(380)
    layout = QVBoxLayout(dlg)

    note = QLabel("The Supplier SKU links to purchase orders.\nPack size describes the bulk carton this product arrives in.")
    note.setStyleSheet("color: grey; font-size: 11px;")
    note.setWordWrap(True)
    layout.addWidget(note)
    layout.addSpacing(6)

    form = QFormLayout()

    inp_sku = QLineEdit(current_sku or "")
    inp_sku.setPlaceholderText("e.g. BIP-BOMBA-240")
    form.addRow("Supplier SKU", inp_sku)

    inp_qty = QSpinBox()
    inp_qty.setMinimum(1)
    inp_qty.setMaximum(9999)
    inp_qty.setValue(current_pack_qty or 1)
    inp_qty.setToolTip("How many units arrive per carton/case")
    form.addRow("Units per Carton", inp_qty)

    inp_unit = QComboBox()
    inp_unit.addItems(['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML'])
    inp_unit.setCurrentText(current_pack_unit or 'EA')
    form.addRow("Unit", inp_unit)

    preview = QLabel()
    preview.setStyleSheet("color: #555; font-style: italic;")

    def update_preview():
        sku = inp_sku.text().strip() or "SKU"
        qty = inp_qty.value()
        unit = inp_unit.currentText()
        preview.setText(f"→  {sku}  ({qty} × {unit} per carton)")

    inp_sku.textChanged.connect(update_preview)
    inp_qty.valueChanged.connect(update_preview)
    inp_unit.currentTextChanged.connect(update_preview)
    update_preview()

    form.addRow("Preview", preview)
    layout.addLayout(form)
    layout.addSpacing(8)

    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)

    from PyQt6.QtGui import QShortcut, QKeySequence
    result = [None]

    def confirm():
        result[0] = (inp_sku.text().strip(), inp_qty.value(), inp_unit.currentText())
        dlg.accept()

    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp_sku.setFocus()
    dlg.exec()
    return result[0]


# ── Reusable popup dialogs ────────────────────────────────────────────

def _text_popup(title, label, current, parent=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(340)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QLineEdit(current)
    inp.selectAll()
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    from PyQt6.QtGui import QShortcut, QKeySequence
    result = [None]
    def confirm():
        v = inp.text().strip()
        if not v:
            QMessageBox.warning(dlg, "Validation", f"{label} cannot be empty.")
            return
        result[0] = v
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def _text_popup_optional(title, label, current, parent=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(340)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QLineEdit(current or "")
    inp.selectAll()
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    from PyQt6.QtGui import QShortcut, QKeySequence
    result = [None]
    def confirm():
        result[0] = inp.text().strip()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def _price_popup(title, label, current, parent=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(280)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QDoubleSpinBox()
    inp.setMaximum(99999)
    inp.setPrefix("$")
    inp.setDecimals(4)
    inp.setValue(float(current))
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    from PyQt6.QtGui import QShortcut, QKeySequence
    result = [None]
    def confirm():
        result[0] = inp.value()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def _number_popup(title, label, current, parent=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(260)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QDoubleSpinBox()
    inp.setMaximum(99999)
    inp.setDecimals(0)
    inp.setValue(float(current))
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    from PyQt6.QtGui import QShortcut, QKeySequence
    result = [None]
    def confirm():
        result[0] = inp.value()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def _choice_popup(title, label, options, current, parent=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(280)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QComboBox()
    inp.addItems(options)
    if current in options:
        inp.setCurrentText(current)
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    from PyQt6.QtGui import QShortcut, QKeySequence
    result = [None]
    def confirm():
        result[0] = inp.currentText()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    dlg.exec()
    return result[0]


class AddAliasDialog(QDialog):
    def __init__(self, master_barcode, parent=None):
        super().__init__(parent)
        self.master_barcode = master_barcode
        self.setWindowTitle("Add Alternate Barcode")
        self.setMinimumWidth(340)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type alternate barcode")
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("e.g. Brand name or variant (optional)")
        form.addRow("Barcode *", self.barcode)
        form.addRow("Note", self.desc)
        layout.addLayout(form)
        layout.addSpacing(8)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Add  [Ctrl+S]")
        ok_btn.setFixedHeight(32)
        ok_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        self.barcode.setFocus()

    def _view_history(self):
        """Open movement history popup for this product."""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
            QTableWidgetItem, QHeaderView, QLabel, QComboBox, QPushButton
        )
        from PyQt6.QtGui import QColor
        from database.connection import get_connection

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Movement History — {self.product['barcode']}")
        dlg.setMinimumSize(820, 500)
        layout = QVBoxLayout(dlg)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Type:"))
        type_cb = QComboBox()
        type_cb.addItems(["ALL", "RECEIPT", "SALE", "ADJUSTMENT", "ADJUSTMENT_IN",
                          "ADJUSTMENT_OUT", "WASTAGE", "SHRINKAGE", "RETURN", "STOCKTAKE"])
        filter_row.addWidget(type_cb)
        filter_row.addStretch()
        status_lbl = QLabel()
        filter_row.addWidget(status_lbl)
        layout.addLayout(filter_row)

        # Table
        tbl = QTableWidget()
        tbl.setColumnCount(6)
        tbl.setHorizontalHeaderLabels(["Date/Time", "Type", "Qty", "Balance", "Reference", "Notes"])
        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        tbl.setColumnWidth(0, 135)
        tbl.setColumnWidth(1, 110)
        tbl.setColumnWidth(2, 60)
        tbl.setColumnWidth(3, 70)
        tbl.setColumnWidth(4, 110)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.setSortingEnabled(False)
        layout.addWidget(tbl)

        def load(move_type=None):
            conn = get_connection()
            sql = """
                SELECT movement_type, quantity, reference, notes, created_at
                FROM stock_movements
                WHERE barcode = ?
            """
            params = [self.barcode]
            if move_type and move_type != "ALL":
                sql += " AND movement_type = ?"
                params.append(move_type)
            sql += " ORDER BY created_at ASC"
            rows = conn.execute(sql, params).fetchall()
            conn.close()

            tbl.setRowCount(0)
            balance = 0.0
            display_rows = []
            for row in rows:
                balance += row["quantity"]
                display_rows.append((row, balance))

            # Show newest first
            for row, bal in reversed(display_rows):
                r = tbl.rowCount()
                tbl.insertRow(r)
                tbl.setItem(r, 0, QTableWidgetItem(str(row["created_at"])[:16]))

                type_item = QTableWidgetItem(row["movement_type"])
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty = row["quantity"]
                if row["movement_type"] in ("RECEIPT", "ADJUSTMENT_IN", "RETURN"):
                    type_item.setForeground(QColor("#4CAF50"))
                elif row["movement_type"] in ("SALE", "WASTAGE", "ADJUSTMENT_OUT", "SHRINKAGE"):
                    type_item.setForeground(QColor("#f85149"))
                else:
                    type_item.setForeground(QColor("steelblue"))
                tbl.setItem(r, 1, type_item)

                qty_item = QTableWidgetItem(f"{'+' if qty > 0 else ''}{qty:.0f}")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty_item.setForeground(QColor("#4CAF50") if qty > 0 else QColor("#f85149"))
                tbl.setItem(r, 2, qty_item)

                bal_item = QTableWidgetItem(f"{bal:.0f}")
                bal_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                bal_item.setForeground(
                    QColor("#4CAF50") if bal > 0 else
                    QColor("#FF9800") if bal == 0 else
                    QColor("#f85149")
                )
                tbl.setItem(r, 3, bal_item)
                tbl.setItem(r, 4, QTableWidgetItem(row["reference"] or ""))
                tbl.setItem(r, 5, QTableWidgetItem(row["notes"] or ""))

            status_lbl.setText(f"{tbl.rowCount()} movements")

        type_cb.currentTextChanged.connect(load)
        load()

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close  [Esc]")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), dlg, dlg.accept)
        dlg.exec()

    def _save(self):
        barcode = self.barcode.text().strip()
        if not barcode:
            QMessageBox.warning(self, "Validation", "Barcode is required.")
            return
        try:
            alias_model.add(barcode, self.master_barcode, self.desc.text().strip())
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not add barcode: {e}")
