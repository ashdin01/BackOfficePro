from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QComboBox,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox, QDoubleSpinBox, QLabel
)
from PyQt6.QtCore import Qt
import models.product as product_model
import models.department as dept_model
import models.supplier as supplier_model


class ProductAdd(QWidget):
    def __init__(self, on_save=None):
        super().__init__()
        self.setWindowTitle("Add Product")
        self.setMinimumWidth(500)
        self.on_save = on_save
        self._depts = dept_model.get_all()
        self._suppliers = supplier_model.get_all()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")
        self.description = QLineEdit()
        self.description.setPlaceholderText("Product description")

        self.dept = QComboBox()
        for d in self._depts:
            self.dept.addItem(d['name'], d['id'])

        self.supplier = QComboBox()
        self.supplier.addItem("-- None --", None)
        for s in self._suppliers:
            self.supplier.addItem(s['name'], s['id'])

        self.unit = QComboBox()
        self.unit.addItems(['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML'])

        self.sell_price = QDoubleSpinBox()
        self.sell_price.setMaximum(99999)
        self.sell_price.setPrefix("$")
        self.sell_price.setDecimals(2)
        self.sell_price.valueChanged.connect(self._update_gp)

        self.cost_price = QDoubleSpinBox()
        self.cost_price.setMaximum(99999)
        self.cost_price.setPrefix("$")
        self.cost_price.setDecimals(2)
        self.cost_price.valueChanged.connect(self._update_gp)

        self.gp_label = QLabel("<b style='color:grey'>—</b>")
        self.gp_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.tax_rate = QComboBox()
        self.tax_rate.addItem("GST Free (0%)", 0.0)
        self.tax_rate.addItem("GST (10%)", 10.0)
        self.tax_rate.setCurrentIndex(1)

        self.reorder_point = QDoubleSpinBox()
        self.reorder_point.setMaximum(99999)
        self.reorder_point.setDecimals(0)

        self.reorder_qty = QDoubleSpinBox()
        self.reorder_qty.setMaximum(99999)
        self.reorder_qty.setDecimals(0)

        self.variable_weight = QCheckBox("Variable weight item (deli/meat)")
        self.expected = QCheckBox("Include in stocktake")
        self.expected.setChecked(True)

        form.addRow("Barcode *", self.barcode)
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
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(35)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _update_gp(self):
        sell = self.sell_price.value()
        cost = self.cost_price.value()
        if sell > 0 and cost >= 0:
            gp = (1 - (cost / sell)) * 100
            color = "green" if gp >= 30 else "orange" if gp >= 15 else "red"
            self.gp_label.setText(f"<b style='color:{color}'>{gp:.1f}%</b>")
        else:
            self.gp_label.setText("<b style='color:grey'>—</b>")

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
            )
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
