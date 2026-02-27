from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QComboBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox,
    QCheckBox, QDoubleSpinBox, QLabel, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox
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
        self.setMinimumHeight(700)
        self.barcode = barcode
        self.on_save = on_save
        self._depts = dept_model.get_all()
        self._suppliers = supplier_model.get_all()
        self.product = product_model.get_by_barcode(barcode)
        self._build_ui()
        self.setup_keyboard()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        p = self.product

        form.addRow("Barcode", QLabel(p['barcode']))

        desc_row = QHBoxLayout()
        self.desc_label = QLabel(p['description'])
        self.desc_label.setWordWrap(True)
        desc_edit_btn = QPushButton("✎")
        desc_edit_btn.setFixedSize(28, 28)
        desc_edit_btn.setToolTip("Edit description")
        desc_edit_btn.clicked.connect(self._edit_description)
        desc_row.addWidget(self.desc_label)
        desc_row.addWidget(desc_edit_btn)
        form.addRow("Description", desc_row)

        self.dept = QComboBox()
        for d in self._depts:
            self.dept.addItem(d['name'], d['id'])
            if d['id'] == p['department_id']:
                self.dept.setCurrentIndex(self.dept.count() - 1)

        self.supplier = QComboBox()
        self.supplier.addItem("-- None --", None)
        for s in self._suppliers:
            self.supplier.addItem(s['name'], s['id'])
            if s['id'] == p['supplier_id']:
                self.supplier.setCurrentIndex(self.supplier.count() - 1)

        self.unit = QComboBox()
        self.unit.addItems(['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML'])
        self.unit.setCurrentText(p['unit'] or 'EA')

        sell_row = QHBoxLayout()
        self.sell_label = QLabel(f"${p['sell_price']:.2f}")
        self._sell_price = p['sell_price']
        sell_edit_btn = QPushButton("✎")
        sell_edit_btn.setFixedSize(28, 28)
        sell_edit_btn.clicked.connect(self._edit_sell_price)
        sell_row.addWidget(self.sell_label)
        sell_row.addWidget(sell_edit_btn)

        cost_row = QHBoxLayout()
        self.cost_label = QLabel(f"${p['cost_price']:.2f}")
        self._cost_price = p['cost_price']
        cost_edit_btn = QPushButton("✎")
        cost_edit_btn.setFixedSize(28, 28)
        cost_edit_btn.clicked.connect(self._edit_cost_price)
        cost_row.addWidget(self.cost_label)
        cost_row.addWidget(cost_edit_btn)

        self.gp_label = QLabel()
        self.gp_label.setTextFormat(Qt.TextFormat.RichText)
        self._update_gp()

        self.tax_rate = QComboBox()
        self.tax_rate.addItem("GST Free (0%)", 0.0)
        self.tax_rate.addItem("GST (10%)", 10.0)
        self.tax_rate.setCurrentIndex(1 if p['tax_rate'] == 10.0 else 0)

        self.reorder_point = QDoubleSpinBox()
        self.reorder_point.setMaximum(99999)
        self.reorder_point.setDecimals(0)
        self.reorder_point.setValue(p['reorder_point'])

        self.reorder_qty = QDoubleSpinBox()
        self.reorder_qty.setMaximum(99999)
        self.reorder_qty.setDecimals(0)
        self.reorder_qty.setValue(p['reorder_qty'])

        self.variable_weight = QCheckBox("Variable weight item (deli/meat)")
        self.variable_weight.setChecked(bool(p['variable_weight']))
        self.expected = QCheckBox("Include in stocktake")
        self.expected.setChecked(bool(p['expected']))
        self.active = QCheckBox("Active")
        self.active.setChecked(bool(p['active']))

        form.addRow("Department *", self.dept)
        form.addRow("Supplier", self.supplier)
        form.addRow("Unit", self.unit)
        form.addRow("Sell Price", sell_row)
        form.addRow("Cost Price", cost_row)
        form.addRow("Gross Profit", self.gp_label)
        form.addRow("Tax Rate", self.tax_rate)
        form.addRow("Reorder Point", self.reorder_point)
        form.addRow("Reorder Qty", self.reorder_qty)
        form.addRow("", self.variable_weight)
        form.addRow("", self.expected)
        form.addRow("", self.active)
        layout.addLayout(form)

        # ── Alternate Barcodes ──────────────────────────
        alias_group = QGroupBox("Alternate Barcodes")
        alias_layout = QVBoxLayout(alias_group)

        self.alias_table = QTableWidget()
        self.alias_table.setColumnCount(3)
        self.alias_table.setHorizontalHeaderLabels(["Barcode", "Description", "Added"])
        self.alias_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.alias_table.setMaximumHeight(150)
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

        # ── Save/Cancel ─────────────────────────────────
        layout.addSpacing(10)
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

    def _load_aliases(self):
        aliases = alias_model.get_aliases(self.barcode)
        self.alias_table.setRowCount(0)
        for a in aliases:
            r = self.alias_table.rowCount()
            self.alias_table.insertRow(r)
            self.alias_table.setItem(r, 0, QTableWidgetItem(a['alias_barcode']))
            self.alias_table.setItem(r, 1, QTableWidgetItem(a['description'] or ''))
            self.alias_table.setItem(r, 2, QTableWidgetItem(a['created_at'][:10]))
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
        reply = QMessageBox.question(self, "Confirm", "Remove this alternate barcode?")
        if reply == QMessageBox.StandardButton.Yes:
            alias_model.delete(alias_id)
            self._load_aliases()

    def _edit_description(self):
        dlg = SingleFieldDialog("Edit Description", "Description",
                                self.desc_label.text(), "text", self)
        if dlg.exec():
            self.desc_label.setText(dlg.value)

    def _edit_sell_price(self):
        dlg = SingleFieldDialog("Edit Sell Price", "Sell Price",
                                self._sell_price, "price", self)
        if dlg.exec():
            self._sell_price = dlg.value
            self.sell_label.setText(f"${self._sell_price:.2f}")
            self._update_gp()

    def _edit_cost_price(self):
        dlg = SingleFieldDialog("Edit Cost Price", "Cost Price",
                                self._cost_price, "price", self)
        if dlg.exec():
            self._cost_price = dlg.value
            self.cost_label.setText(f"${self._cost_price:.2f}")
            self._update_gp()

    def _update_gp(self):
        sell = self._sell_price
        cost = self._cost_price
        if sell > 0:
            gp = (1 - (cost / sell)) * 100
            color = "green" if gp >= 30 else "orange" if gp >= 15 else "red"
            self.gp_label.setText(f"<b style='color:{color}'>{gp:.1f}%</b>")
        else:
            self.gp_label.setText("<b style='color:grey'>--</b>")

    def _save(self):
        description = self.desc_label.text().strip()
        if not description:
            QMessageBox.warning(self, "Validation", "Description is required.")
            return
        try:
            product_model.update(
                barcode=self.barcode,
                description=description,
                department_id=self.dept.currentData(),
                supplier_id=self.supplier.currentData(),
                unit=self.unit.currentText(),
                sell_price=self._sell_price,
                cost_price=self._cost_price,
                tax_rate=self.tax_rate.currentData(),
                reorder_point=self.reorder_point.value(),
                reorder_qty=self.reorder_qty.value(),
                variable_weight=int(self.variable_weight.isChecked()),
                expected=int(self.expected.isChecked()),
                active=int(self.active.isChecked()),
            )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


class AddAliasDialog(QDialog):
    def __init__(self, master_barcode, parent=None):
        super().__init__(parent)
        self.master_barcode = master_barcode
        self.setWindowTitle("Add Alternate Barcode")
        self.setMinimumWidth(360)
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

        layout.addSpacing(10)
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


class SingleFieldDialog(QDialog):
    def __init__(self, title, label, current_value, field_type="text", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(320)
        self.field_type = field_type
        self.value = current_value
        self._build_ui(label, current_value)

    def _build_ui(self, label, current_value):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        if self.field_type == "price":
            self.input = QDoubleSpinBox()
            self.input.setMaximum(99999)
            self.input.setPrefix("$")
            self.input.setDecimals(2)
            self.input.setValue(float(current_value))
        else:
            self.input = QLineEdit()
            self.input.setText(str(current_value))
            self.input.selectAll()
        form.addRow(label, self.input)
        layout.addLayout(form)
        layout.addSpacing(10)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Save  [Ctrl+S]")
        ok_btn.setFixedHeight(32)
        ok_btn.clicked.connect(self._confirm)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self, self._confirm)
        self.input.setFocus()

    def _confirm(self):
        if self.field_type == "price":
            self.value = self.input.value()
        else:
            v = self.input.text().strip()
            if not v:
                QMessageBox.warning(self, "Validation", "Field cannot be empty.")
                return
            self.value = v
        self.accept()
