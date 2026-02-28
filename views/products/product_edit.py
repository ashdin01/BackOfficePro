from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox,
    QDoubleSpinBox, QLabel, QDialog, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QCheckBox
)
from PyQt6.QtCore import Qt
from utils.keyboard_mixin import KeyboardMixin
import models.product as product_model
import models.department as dept_model
import models.supplier as supplier_model
import models.barcode_alias as alias_model


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
        self.product = product_model.get_by_barcode(barcode)
        self._init_values()
        self._build_ui()
        self.setup_keyboard()

    def _init_values(self):
        p = self.product
        self._description  = p['description']
        self._dept_id      = p['department_id']
        self._supplier_id  = p['supplier_id']
        self._unit         = p['unit'] or 'EA'
        self._sell_price   = p['sell_price']
        self._cost_price   = p['cost_price']
        self._tax_rate     = p['tax_rate']
        self._reorder_point= p['reorder_point']
        self._reorder_qty  = p['reorder_qty']
        self._variable_wt  = bool(p['variable_weight'])
        self._in_stocktake = bool(p['expected'])
        self._active       = bool(p['active'])

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        # Helper to make a read-only row with ✎ button
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

        form.addRow("Barcode", QLabel(self.product['barcode']))

        r, self.lbl_desc = ro_row(self._description, self._edit_description)
        form.addRow("Description", r)

        r, self.lbl_dept = ro_row(self._dept_name(), self._edit_dept)
        form.addRow("Department", r)

        r, self.lbl_supplier = ro_row(self._supplier_name(), self._edit_supplier)
        form.addRow("Supplier", r)

        r, self.lbl_unit = ro_row(self._unit, self._edit_unit)
        form.addRow("Unit", r)

        r, self.lbl_sell = ro_row(f"${self._sell_price:.2f}", self._edit_sell)
        form.addRow("Sell Price", r)

        r, self.lbl_cost = ro_row(f"${self._cost_price:.2f}", self._edit_cost)
        form.addRow("Cost Price", r)

        self.lbl_gp = QLabel()
        self.lbl_gp.setTextFormat(Qt.TextFormat.RichText)
        self._refresh_gp()
        form.addRow("Gross Profit", self.lbl_gp)

        r, self.lbl_tax = ro_row(self._tax_label(), self._edit_tax)
        form.addRow("Tax Rate", r)

        r, self.lbl_reorder_pt = ro_row(int(self._reorder_point), self._edit_reorder_point)
        form.addRow("Reorder Point", r)

        r, self.lbl_reorder_qty = ro_row(int(self._reorder_qty), self._edit_reorder_qty)
        form.addRow("Reorder Qty", r)

        r, self.lbl_vw = ro_row("Yes" if self._variable_wt else "No", self._edit_variable_wt)
        form.addRow("Variable Weight", r)

        r, self.lbl_stocktake = ro_row("Yes" if self._in_stocktake else "No", self._edit_stocktake)
        form.addRow("Include in Stocktake", r)

        r, self.lbl_active = ro_row("Yes" if self._active else "No", self._edit_active)
        form.addRow("Active", r)

        layout.addLayout(form)

        # Alternate barcodes
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

    # ── Edit popup helpers ────────────────────────────────────────────

    def _edit_description(self):
        val = _text_popup("Edit Description", "Description", self._description, self)
        if val is not None:
            self._description = val
            self.lbl_desc.setText(val)

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
            self.lbl_cost.setText(f"${val:.2f}")
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

    def _edit_reorder_qty(self):
        val = _number_popup("Edit Reorder Qty", "Reorder Qty", self._reorder_qty, self)
        if val is not None:
            self._reorder_qty = val
            self.lbl_reorder_qty.setText(str(int(val)))

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

    def _save(self):
        if not self._description.strip():
            QMessageBox.warning(self, "Validation", "Description is required.")
            return
        try:
            product_model.update(
                barcode=self.barcode,
                description=self._description,
                department_id=self._dept_id,
                supplier_id=self._supplier_id,
                unit=self._unit,
                sell_price=self._sell_price,
                cost_price=self._cost_price,
                tax_rate=self._tax_rate,
                reorder_point=self._reorder_point,
                reorder_qty=self._reorder_qty,
                variable_weight=int(self._variable_wt),
                expected=int(self._in_stocktake),
                active=int(self._active),
            )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


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


def _price_popup(title, label, current, parent=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(280)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QDoubleSpinBox()
    inp.setMaximum(99999)
    inp.setPrefix("$")
    inp.setDecimals(2)
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
