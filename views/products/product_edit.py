from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QComboBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox, QDoubleSpinBox, QLabel
)
from PyQt6.QtCore import Qt
from utils.keyboard_mixin import KeyboardMixin
import models.product as product_model
import models.department as dept_model
import models.supplier as supplier_model


class ProductEdit(KeyboardMixin, QWidget):
    def __init__(self, barcode, on_save=None):
        super().__init__()
        self.setWindowTitle("Product Detail")
        self.setMinimumWidth(500)
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
        self.description = QLineEdit(p['description'])

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

        self.sell_price = QDoubleSpinBox()
        self.sell_price.setMaximum(99999)
        self.sell_price.setPrefix("$")
        self.sell_price.setDecimals(2)
        self.sell_price.setValue(p['sell_price'])
        self.sell_price.valueChanged.connect(self._update_gp)

        self.cost_price = QDoubleSpinBox()
        self.cost_price.setMaximum(99999)
        self.cost_price.setPrefix("$")
        self.cost_price.setDecimals(2)
        self.cost_price.setValue(p['cost_price'])
        self.cost_price.valueChanged.connect(self._update_gp)

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

        form.addRow("Description *", self.description)
        form.addRow("Department *", self.dept)
        form.addRow("Supplier", self.supplier)
        form.addRow("Unit", self.unit)
        form.addRow("Sell Price", self.sell_price)
        form.addRow("Cost Price", self.cost_price)
        form.addRow("Gross Profit", self.gp_label)
        form.addRow("Tax Rate", self.tax_rate)
        form.addRow("Reorder Point", self.reorder_point)
        form.addRow("Reorder Qty", self.reorder_qty)
        form.addRow("", self.variable_weight)
        form.addRow("", self.expected)
        form.addRow("", self.active)
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        save_btn = QPushButton("&Save")
        save_btn.setFixedHeight(35)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("&Cancel")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

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
        description = self.description.text().strip()
        if not description:
            QMessageBox.warning(self, "Validation", "Description is required.")
            return
        try:
            product_model.update(
                barcode=self.barcode, description=description,
                department_id=self.dept.currentData(),
                supplier_id=self.supplier.currentData(),
                unit=self.unit.currentText(),
                sell_price=self.sell_price.value(),
                cost_price=self.cost_price.value(),
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
