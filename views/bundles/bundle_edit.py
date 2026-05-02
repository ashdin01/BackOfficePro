from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QSpinBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut, QKeySequence
import models.bundle as bundle_model


class BundleEdit(QWidget):
    def __init__(self, bundle_id=None, on_save=None):
        super().__init__()
        self.bundle_id = bundle_id
        self.on_save = on_save
        self._bundle = bundle_model.get_by_id(bundle_id) if bundle_id else None
        self.setWindowTitle("Edit Bundle" if bundle_id else "Add Bundle")
        self.setMinimumWidth(620)
        self.setMinimumHeight(520)
        self.resize(680, 580)
        self._build_ui()
        if self._bundle:
            self._load_eligible()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── Header ───────────────────────────────────────────────────────
        title = QLabel("Edit Bundle" if self.bundle_id else "New Bundle")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #e6edf3;")
        layout.addWidget(title)

        # ── Fields ───────────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(8)

        self._name = QLineEdit(self._bundle['name'] if self._bundle else '')
        self._name.setPlaceholderText("e.g. Mixed Cider Case")
        form.addRow("Name *", self._name)

        self._desc = QLineEdit(self._bundle['description'] if self._bundle else '')
        self._desc.setPlaceholderText("Optional description")
        form.addRow("Description", self._desc)

        self._req_qty = QSpinBox()
        self._req_qty.setMinimum(1)
        self._req_qty.setMaximum(999)
        self._req_qty.setValue(self._bundle['required_qty'] if self._bundle else 4)
        self._req_qty.setToolTip("How many eligible items must be scanned to trigger the bundle price")
        form.addRow("Required Qty *", self._req_qty)

        self._price = QDoubleSpinBox()
        self._price.setPrefix("$")
        self._price.setMaximum(99999)
        self._price.setDecimals(2)
        self._price.setValue(self._bundle['price'] if self._bundle else 0.0)
        form.addRow("Bundle Price *", self._price)

        self._active = QCheckBox("Active")
        self._active.setChecked(bool(self._bundle['active']) if self._bundle else True)
        form.addRow("", self._active)

        layout.addLayout(form)

        # ── Eligible items ────────────────────────────────────────────────
        elig_label = QLabel("Eligible Items")
        elig_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #e6edf3; margin-top: 8px;")
        layout.addWidget(elig_label)

        elig_note = QLabel(
            "Any of these barcodes can contribute towards the bundle. "
            "When the required quantity is reached the bundle price applies."
        )
        elig_note.setStyleSheet("color: #8b949e; font-size: 11px;")
        elig_note.setWordWrap(True)
        layout.addWidget(elig_note)

        self._elig_table = QTableWidget()
        self._elig_table.setColumnCount(4)
        self._elig_table.setHorizontalHeaderLabels(["Barcode", "Description", "Units/Pack", ""])
        self._elig_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._elig_table.setColumnWidth(0, 150)
        self._elig_table.setColumnWidth(2, 90)
        self._elig_table.setColumnWidth(3, 40)
        self._elig_table.setMaximumHeight(200)
        self._elig_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._elig_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._elig_table.verticalHeader().setVisible(False)
        layout.addWidget(self._elig_table)

        # Add eligible item row
        add_row = QHBoxLayout()
        self._bc_input = QLineEdit()
        self._bc_input.setPlaceholderText("Barcode — scan or type, then press Add")
        self._bc_input.setFixedHeight(32)
        self._bc_input.returnPressed.connect(self._add_eligible)
        add_row.addWidget(self._bc_input)
        btn_add_elig = QPushButton("+ Add Item")
        btn_add_elig.setFixedHeight(32)
        btn_add_elig.setFixedWidth(110)
        btn_add_elig.clicked.connect(self._add_eligible)
        add_row.addWidget(btn_add_elig)
        layout.addLayout(add_row)

        # ── Action bar ────────────────────────────────────────────────────
        layout.addStretch()
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save  [Ctrl+S]")
        save_btn.setFixedHeight(34)
        save_btn.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border: none; "
            "border-radius: 4px; padding: 0 20px; font-weight: bold; }"
            "QPushButton:hover { background: #1976d2; }"
        )
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load_eligible(self):
        self._elig_table.setRowCount(0)
        for item in bundle_model.get_eligible(self.bundle_id):
            self._add_eligible_row(item['id'], item['barcode'], item['description'], dict(item).get('unit_qty', 1))

    def _add_eligible_row(self, item_id, barcode, description, unit_qty=1):
        r = self._elig_table.rowCount()
        self._elig_table.insertRow(r)
        bc_item = QTableWidgetItem(barcode)
        bc_item.setData(Qt.ItemDataRole.UserRole, item_id)
        self._elig_table.setItem(r, 0, bc_item)
        self._elig_table.setItem(r, 1, QTableWidgetItem(description or ''))
        sb = QSpinBox()
        sb.setMinimum(1)
        sb.setMaximum(999)
        sb.setValue(int(unit_qty) if unit_qty else 1)
        sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        sb.setFixedHeight(24)
        sb.setToolTip("How many base units this scan contributes (1 for single, 6 for 6-pack, etc.)")
        if item_id and item_id > 0:
            sb.valueChanged.connect(lambda v, eid=item_id: bundle_model.update_eligible_unit_qty(eid, v))
        self._elig_table.setCellWidget(r, 2, sb)
        btn_rem = QPushButton("✕")
        btn_rem.setFixedHeight(24)
        btn_rem.setStyleSheet("color: #f44336; font-weight: bold; border: none; background: transparent;")
        btn_rem.clicked.connect(lambda _, eid=item_id: self._remove_eligible(eid))
        self._elig_table.setCellWidget(r, 3, btn_rem)

    def _add_eligible(self):
        barcode = self._bc_input.text().strip()
        if not barcode:
            return

        # Check for duplicate in table
        for row in range(self._elig_table.rowCount()):
            if self._elig_table.item(row, 0).text() == barcode:
                QMessageBox.warning(self, "Duplicate", f"Barcode {barcode} is already in the list.")
                self._bc_input.clear()
                return

        description = bundle_model.resolve_barcode_description(barcode)
        unit_qty = bundle_model.resolve_barcode_unit_qty(barcode)

        if self.bundle_id:
            # Saved bundle — persist immediately
            bundle_model.add_eligible(self.bundle_id, barcode, description, unit_qty)
            row_id = None
            from database.connection import get_connection
            conn = get_connection()
            try:
                r = conn.execute(
                    "SELECT id FROM bundle_eligible WHERE bundle_id=? AND barcode=?",
                    (self.bundle_id, barcode)
                ).fetchone()
                row_id = r['id'] if r else None
            finally:
                conn.close()
            self._add_eligible_row(row_id, barcode, description, unit_qty)
        else:
            # New bundle — buffer in table with sentinel id=-1
            self._add_eligible_row(-1, barcode, description, unit_qty)

        self._bc_input.clear()

    def _remove_eligible(self, item_id):
        if item_id and item_id > 0:
            bundle_model.remove_eligible(item_id)
        # Remove from table
        for row in range(self._elig_table.rowCount()):
            if self._elig_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == item_id:
                self._elig_table.removeRow(row)
                break

    def _save(self):
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Bundle name is required.")
            return

        desc = self._desc.text().strip()
        req_qty = self._req_qty.value()
        price = self._price.value()
        active = self._active.isChecked()

        if self.bundle_id:
            bundle_model.update(self.bundle_id, name, desc, req_qty, price, active)
        else:
            self.bundle_id = bundle_model.add(name, desc, req_qty, price)
            # Persist any buffered eligible items
            for row in range(self._elig_table.rowCount()):
                barcode = self._elig_table.item(row, 0).text()
                description = self._elig_table.item(row, 1).text()
                sb = self._elig_table.cellWidget(row, 2)
                unit_qty = sb.value() if sb else 1
                bundle_model.add_eligible(self.bundle_id, barcode, description, unit_qty)

        if self.on_save:
            self.on_save()
        self.close()
