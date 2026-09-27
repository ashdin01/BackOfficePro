from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QDoubleSpinBox,
    QDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut, QKeySequence
import config.styles as styles
import controllers.product_controller as product_controller
from utils.error_dialog import show_error
from utils.money_field import money_field


class SellingUnitsPanel(QGroupBox):
    """Alternate pack sizes (case, 6-pack, etc.) that draw from a product's
    base stock — the "Selling Units" section embedded in ProductEdit.

    `get_master_sell_price` is a callable rather than a fixed number so that
    if the user edits the base Sell Price earlier in the same ProductEdit
    session, a newly-added selling unit's price still defaults from the
    current value, not a stale one snapshotted at panel-construction time.
    """

    def __init__(self, barcode, get_master_sell_price, parent=None):
        super().__init__("Selling Units  (case, 6-pack, etc.)", parent)
        self.barcode = barcode
        self._get_master_sell_price = get_master_sell_price
        self._build_ui()
        self._load_selling_units()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        note = QLabel(
            "Define alternate pack sizes that draw from this product's base stock. "
            "Each unit sold deducts the configured quantity from stock on hand."
        )
        note.setStyleSheet(styles.STYLE_LABEL_MUTED)
        note.setWordWrap(True)
        lay.addWidget(note)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Barcode", "PLU", "Name", "Units / Pack", "Sell Price", "", ""]
        )
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 70)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 36)
        self.table.setColumnWidth(6, 36)
        self.table.setMaximumHeight(150)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add Selling Unit")
        btn_add.setFixedHeight(28)
        btn_add.clicked.connect(self._add_selling_unit_popup)
        btn_row.addWidget(btn_add)
        btn_row.addStretch()
        lay.addLayout(btn_row)

    def _load_selling_units(self):
        rows = product_controller.get_selling_units(self.barcode)
        self.table.setRowCount(0)
        for su in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)

            bc_item = QTableWidgetItem(su['barcode'] or '—')
            bc_item.setData(Qt.ItemDataRole.UserRole, su['id'])
            self.table.setItem(r, 0, bc_item)

            plu_item = QTableWidgetItem(su['plu'] or '—')
            plu_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 1, plu_item)

            self.table.setItem(r, 2, QTableWidgetItem(su['label']))

            qty_item = QTableWidgetItem(f"×{int(su['unit_qty']) if su['unit_qty'] == int(su['unit_qty']) else su['unit_qty']}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, qty_item)

            price_item = QTableWidgetItem(f"${su['sell_price']:.2f}")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 4, price_item)

            btn_edit = QPushButton("✎")
            btn_edit.setFixedHeight(24)
            btn_edit.setStyleSheet(styles.STYLE_BTN_INFO_LINK)
            btn_edit.clicked.connect(lambda _, sid=su['id']: self._edit_selling_unit_popup(sid))
            self.table.setCellWidget(r, 5, btn_edit)

            btn_rem = QPushButton("✕")
            btn_rem.setFixedHeight(24)
            btn_rem.setStyleSheet(styles.STYLE_BTN_DANGER_LINK)
            btn_rem.clicked.connect(lambda _, sid=su['id']: self._remove_selling_unit(sid))
            self.table.setCellWidget(r, 6, btn_rem)

    def _add_selling_unit_popup(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Selling Unit")
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        lbl_input = QLineEdit()
        lbl_input.setPlaceholderText('e.g. "Case (24×375ml)"')
        form.addRow("Label *", lbl_input)

        qty_spin = QDoubleSpinBox()
        qty_spin.setMinimum(1)
        qty_spin.setMaximum(9999)
        qty_spin.setDecimals(0)
        qty_spin.setValue(6)
        form.addRow("Units per pack *", qty_spin)

        plu_input = QLineEdit()
        plu_input.setPlaceholderText("e.g. 134 (optional)")
        form.addRow("PLU", plu_input)

        bc_input = QLineEdit()
        bc_input.setPlaceholderText("Scan or type (optional)")
        form.addRow("Barcode", bc_input)

        price_spin = QDoubleSpinBox()
        price_spin.setMaximum(99999)
        price_spin.setDecimals(2)
        price_spin.setValue(round(self._get_master_sell_price() * 6, 2))
        form.addRow("Sell Price *", money_field(price_spin))

        lay.addLayout(form)
        lay.addSpacing(4)

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
        lay.addLayout(btns)

        def confirm():
            label = lbl_input.text().strip()
            if not label:
                QMessageBox.warning(dlg, "Validation", "Label is required.")
                return
            barcode_val = bc_input.text().strip() or None
            plu_val = plu_input.text().strip() or None
            try:
                product_controller.add_selling_unit(
                    self.barcode, barcode_val, plu_val, label,
                    qty_spin.value(), price_spin.value()
                )
            except Exception as e:
                show_error(dlg, "Could not save selling unit.", e)
                return
            self._load_selling_units()
            dlg.accept()

        ok_btn.clicked.connect(confirm)
        cancel_btn.clicked.connect(dlg.reject)
        QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
        QShortcut(QKeySequence("Escape"), dlg, dlg.reject)

        # Pre-fill price hint when qty changes
        qty_spin.valueChanged.connect(
            lambda v: price_spin.setValue(round(self._get_master_sell_price() * v, 2))
        )

        lbl_input.setFocus()
        dlg.exec()

    def _edit_selling_unit_popup(self, su_id: int):
        su = product_controller.get_selling_unit_by_id(su_id)
        if not su:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Selling Unit")
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        lbl_input = QLineEdit(su['label'])
        form.addRow("Name *", lbl_input)

        qty_spin = QDoubleSpinBox()
        qty_spin.setMinimum(1)
        qty_spin.setMaximum(9999)
        qty_spin.setDecimals(0)
        qty_spin.setValue(su['unit_qty'])
        form.addRow("Units per pack *", qty_spin)

        plu_input = QLineEdit(su['plu'] or '')
        plu_input.setPlaceholderText("e.g. 134 (optional)")
        form.addRow("PLU", plu_input)

        bc_input = QLineEdit(su['barcode'] or '')
        bc_input.setPlaceholderText("Scan or type (optional)")
        form.addRow("Barcode", bc_input)

        price_spin = QDoubleSpinBox()
        price_spin.setMaximum(99999)
        price_spin.setDecimals(2)
        price_spin.setValue(su['sell_price'])
        form.addRow("Sell Price *", money_field(price_spin))

        lay.addLayout(form)
        lay.addSpacing(4)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("Save  [Ctrl+S]")
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
        lay.addLayout(btns)

        def confirm():
            label = lbl_input.text().strip()
            if not label:
                QMessageBox.warning(dlg, "Validation", "Name is required.")
                return
            barcode_val = bc_input.text().strip() or None
            plu_val = plu_input.text().strip() or None
            try:
                product_controller.update_selling_unit(
                    su_id, label, qty_spin.value(), plu_val, barcode_val, price_spin.value()
                )
            except Exception as e:
                show_error(dlg, "Could not update selling unit.", e)
                return
            self._load_selling_units()
            dlg.accept()

        ok_btn.clicked.connect(confirm)
        cancel_btn.clicked.connect(dlg.reject)
        QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
        dlg.exec()

    def _remove_selling_unit(self, su_id: int):
        if QMessageBox.question(
            self, "Remove", "Remove this selling unit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        product_controller.delete_selling_unit(su_id)
        self._load_selling_units()
