from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QComboBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox,
    QDoubleSpinBox, QLabel, QSpinBox
)
from PyQt6.QtCore import Qt
from utils.keyboard_mixin import KeyboardMixin
import models.product as product_model
import models.department as dept_model
import models.supplier as supplier_model
import models.group as group_model


class ProductAdd(KeyboardMixin, QWidget):
    def __init__(self, on_save=None):
        super().__init__()
        self.setWindowTitle("Add Product")
        self.setMinimumWidth(500)
        self.on_save = on_save
        self._depts = dept_model.get_all()
        self._suppliers = supplier_model.get_all()
        self._groups = group_model.get_all(active_only=True)
        self._build_ui()
        self.setup_keyboard()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")

        self.description = QLineEdit()
        self.description.setPlaceholderText("Product description")

        self.brand = QLineEdit()
        self.brand.setPlaceholderText("Brand name (optional)")

        self.plu = QLineEdit()
        self.plu.setPlaceholderText("PLU / POS code (optional)")

        self.supplier = QComboBox()
        self.supplier.addItem("-- None --", None)
        for s in self._suppliers:
            self.supplier.addItem(s['name'], s['id'])

        self.supplier_sku = QLineEdit()
        self.supplier_sku.setPlaceholderText("Supplier's SKU (optional)")

        self.pack_qty = QSpinBox()
        self.pack_qty.setMinimum(1)
        self.pack_qty.setMaximum(9999)
        self.pack_qty.setValue(1)
        self.pack_qty.setToolTip("How many units arrive per carton/case")

        self.pack_unit = QComboBox()
        self.pack_unit.addItems(['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML'])

        pack_row = QHBoxLayout()
        pack_row.addWidget(self.pack_qty)
        pack_row.addWidget(QLabel("×"))
        pack_row.addWidget(self.pack_unit)
        pack_row.addWidget(QLabel("per carton"))
        pack_row.addStretch()

        self.dept = QComboBox()
        for d in self._depts:
            self.dept.addItem(d['name'], d['id'])
        self.dept.currentIndexChanged.connect(self._on_dept_changed)

        self.group = QComboBox()
        self.group.addItem("— No Group —", None)
        for g in self._groups:
            self.group.addItem(f"{g['dept_name']} › {g['name']}", g['id'])

        self.unit = QComboBox()
        self.unit.addItems(['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML'])

        self.cost_price = QDoubleSpinBox()
        self.cost_price.setMaximum(99999)
        self.cost_price.setPrefix("$")
        self.cost_price.setDecimals(2)
        self.cost_price.valueChanged.connect(self._update_gp)

        self.sell_price = QDoubleSpinBox()
        self.sell_price.setMaximum(99999)
        self.sell_price.setPrefix("$")
        self.sell_price.setDecimals(2)
        self.sell_price.valueChanged.connect(self._update_gp)

        self.gp_label = QLabel("<b style='color:grey'>--</b>")
        self.gp_label.setTextFormat(Qt.TextFormat.RichText)

        self.tax_rate = QComboBox()
        self.tax_rate.addItem("GST Free (0%)", 0.0)
        self.tax_rate.addItem("GST (10%)", 10.0)
        self.tax_rate.setCurrentIndex(1)

        self.reorder_point = QDoubleSpinBox()
        self.reorder_point.setMaximum(99999)
        self.reorder_point.setDecimals(0)

        self.reorder_max = QDoubleSpinBox()
        self.reorder_max.setMaximum(99999)
        self.reorder_max.setDecimals(0)
        self.reorder_max.setToolTip("Maximum stock level. Order qty = Max - On Hand.")


        self.variable_weight = QCheckBox("Variable weight item (deli/meat)")
        self.expected = QCheckBox("Include in stocktake")
        self.expected.setChecked(True)

        # ── Field order per spec ──────────────────────────────────────
        form.addRow("Barcode *",        self.barcode)
        form.addRow("Description *",    self.description)
        form.addRow("Brand",            self.brand)
        form.addRow("PLU",              self.plu)
        form.addRow("Supplier",         self.supplier)
        form.addRow("Supplier SKU",     self.supplier_sku)
        form.addRow("Units per Carton", pack_row)
        form.addRow("Department *",     self.dept)
        form.addRow("Group",            self.group)
        form.addRow("Unit",             self.unit)
        form.addRow("Cost Price",       self.cost_price)
        form.addRow("Sell Price",       self.sell_price)
        form.addRow("Gross Profit",     self.gp_label)
        form.addRow("Tax Rate",         self.tax_rate)
        form.addRow("Reorder Point (Min)", self.reorder_point)
        form.addRow("Reorder Max",            self.reorder_max)
        form.addRow("",                 self.variable_weight)
        form.addRow("",                 self.expected)

        layout.addLayout(form)
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

    def _on_dept_changed(self):
        dept_id = self.dept.currentData()
        self.group.clear()
        self.group.addItem("— No Group —", None)
        for g in self._groups:
            if g['department_id'] == dept_id:
                self.group.addItem(g['name'], g['id'])

    def _update_gp(self):
        sell = self.sell_price.value()
        cost = self.cost_price.value()
        if sell > 0:
            gp = (1 - (cost / sell)) * 100
            color = "green" if gp >= 30 else "orange" if gp >= 15 else "red"
            self.gp_label.setText(f"<b style='color:{color}'>{gp:.1f}%</b>")
        else:
            self.gp_label.setText("<b style='color:grey'>--</b>")

    def _save(self):
        barcode = self.barcode.text().strip()
        description = self.description.text().strip()
        if not barcode or not description:
            QMessageBox.warning(self, "Validation", "Barcode and Description are required.")
            return
        try:
            product_model.add(
                barcode=barcode,
                description=description,
                brand=self.brand.text().strip(),
                plu=self.plu.text().strip(),
                supplier_sku=self.supplier_sku.text().strip(),
                pack_qty=self.pack_qty.value(),
                pack_unit=self.pack_unit.currentText(),
                group_id=self.group.currentData(),
                department_id=self.dept.currentData(),
                supplier_id=self.supplier.currentData(),
                unit=self.unit.currentText(),
                sell_price=self.sell_price.value(),
                cost_price=self.cost_price.value(),
                tax_rate=self.tax_rate.currentData(),
                reorder_point=self.reorder_point.value(),
                reorder_max=self.reorder_max.value(),
                variable_weight=int(self.variable_weight.isChecked()),
                expected=int(self.expected.isChecked()),
            )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
