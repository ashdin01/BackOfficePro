from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QFrame,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox,
    QDoubleSpinBox, QLabel, QDialog, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QCheckBox, QSpinBox, QFileDialog, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from utils.keyboard_mixin import KeyboardMixin
import os, shutil
import controllers.product_controller as product_controller
import models.product as product_model
from PyQt6.QtGui import QColor
import models.department as dept_model
import models.supplier as supplier_model
import models.barcode_alias as alias_model
import models.group as group_model


class ProductEdit(KeyboardMixin, QWidget):
    def __init__(self, barcode, on_save=None):
        super().__init__()
        self.setWindowTitle("Product Detail")
        self.setMinimumWidth(900)
        self.setMinimumHeight(700)
        self.resize(960, 860)
        self.barcode = barcode
        self.on_save = on_save
        self._depts = dept_model.get_all()
        self._suppliers = supplier_model.get_all()
        self._groups = group_model.get_all(active_only=False)
        self.product = product_model.get_by_barcode(barcode)
        self._init_values()
        self._build_ui()
        self.setup_keyboard()

    def _check_selling_unit(self):
        from database.connection import get_connection as _gc
        conn = _gc()
        try:
            row = conn.execute(
                """
                SELECT su.master_barcode, su.label, su.unit_qty,
                       p.description AS master_desc
                FROM product_selling_units su
                JOIN products p ON su.master_barcode = p.barcode
                WHERE su.barcode = ? AND su.active = 1
                """,
                (self.barcode,)
            ).fetchone()
            if row:
                self._is_selling_unit = True
                self._su_master = dict(row)
            else:
                self._is_selling_unit = False
                self._su_master = None
        finally:
            conn.close()

    def _selling_unit_guard(self) -> bool:
        """Returns True (and shows warning) if this product is a selling unit — caller should abort edit."""
        if self._is_selling_unit:
            m = self._su_master
            QMessageBox.information(
                self, "Selling Unit — Read Only",
                f"This product is a selling unit of:\n\n"
                f"  {m['master_desc']}  ({m['master_barcode']})\n\n"
                "Pricing, PLU, description and barcode are managed on the master product.\n"
                "Open the master product to make changes."
            )
            return True
        return False

    def _init_values(self):
        self._check_selling_unit()
        p = self.product
        self._description   = p['description']
        self._brand         = p['brand'] or ''
        self._plu           = p['plu'] or '' if 'plu' in p.keys() else ''
        self._supplier_sku  = p['supplier_sku'] or ''
        self._pack_qty      = int(p['pack_qty']) if 'pack_qty' in p.keys() and p['pack_qty'] else 1
        self._pack_unit     = p['pack_unit'] if 'pack_unit' in p.keys() and p['pack_unit'] else 'EA'
        self._group_id      = p['group_id'] if 'group_id' in p.keys() else None
        self._dept_id       = p['department_id']
        self._supplier_id   = p['supplier_id']
        self._product_suppliers = self._load_product_suppliers()
        self._unit          = p['unit'] or 'EA'
        self._sell_price    = p['sell_price']
        self._cost_price    = p['cost_price']
        self._tax_rate      = p['tax_rate']
        self._reorder_point = p['reorder_point']
        self._reorder_max   = p['reorder_max'] if 'reorder_max' in p.keys() and p['reorder_max'] else 0
        self._variable_wt   = bool(p['variable_weight'])
        self._in_stocktake  = bool(p['expected'])
        self._active        = bool(p['active'])
        self._auto_reorder  = bool(p['auto_reorder']) if 'auto_reorder' in p.keys() else False

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if self._is_selling_unit:
            m = self._su_master
            banner = QLabel(
                f"⚠  Selling unit of:  {m['master_desc']}  —  barcode {m['master_barcode']}  "
                f"({int(m['unit_qty'])} units per pack).  "
                "Pricing, PLU and description are managed on the master product."
            )
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "background: #3a2a00; color: #ffcc44; border: 1px solid #7a5a00;"
                "border-radius: 6px; padding: 8px 12px; font-size: 12px;"
            )
            layout.addWidget(banner)

        def ro_row(field_label, value, on_edit):
            row = QHBoxLayout()
            btn = QPushButton("✎")
            btn.setFixedSize(28, 28)
            btn.clicked.connect(on_edit)
            key = QLabel(field_label)
            key.setMinimumWidth(130)
            key.setStyleSheet('color: #8b949e;')
            lbl = QLabel(str(value))
            lbl.setMinimumWidth(180)
            row.addWidget(btn)
            row.addWidget(key)
            row.addWidget(lbl)
            row.addStretch()
            return row, lbl

        def info_row(field_label, widget):
            row = QHBoxLayout()
            stub = QPushButton()
            stub.setFixedSize(28, 28)
            stub.setEnabled(False)
            stub.setStyleSheet("background: transparent; border: none;")
            key = QLabel(field_label)
            key.setMinimumWidth(130)
            key.setStyleSheet("color: #8b949e;")
            row.addWidget(stub)
            row.addWidget(key)
            row.addWidget(widget)
            row.addStretch()
            return row

        # ── Two-column field area ─────────────────────────────────────
        two_col = QHBoxLayout()
        two_col.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(5)
        right_col = QVBoxLayout()
        right_col.setSpacing(5)

        # Left — identification & classification
        r, self.lbl_barcode = ro_row("Barcode", self.product['barcode'], self._edit_barcode)
        left_col.addLayout(r)

        r, self.lbl_desc = ro_row("Description", self._description, self._edit_description)
        left_col.addLayout(r)

        r, self.lbl_brand = ro_row("Brand", self._brand or "—", self._edit_brand)
        left_col.addLayout(r)

        r, self.lbl_plu = ro_row("PLU", self._plu or "—", self._edit_plu)
        left_col.addLayout(r)

        r, self.lbl_supplier = ro_row("Supplier (default)", self._supplier_name(), self._edit_supplier)
        left_col.addLayout(r)

        r, self.lbl_supplier_sku = ro_row("Supplier SKU", self._supplier_sku_display(), self._edit_supplier_sku)
        left_col.addLayout(r)

        r, self.lbl_dept = ro_row("Department", self._dept_name(), self._edit_dept)
        left_col.addLayout(r)

        r, self.lbl_group = ro_row("Group", self._group_name(), self._edit_group)
        left_col.addLayout(r)

        r, self.lbl_unit = ro_row("Unit", self._unit, self._edit_unit)
        left_col.addLayout(r)

        left_col.addStretch()

        # Right — pricing, stock & flags
        r, self.lbl_cost = ro_row("Cost Price (ex GST)", f"${self._cost_price:.4f}", self._edit_cost)
        right_col.addLayout(r)

        tax = self._tax_rate or 0.0
        inc = self._cost_price * (1 + tax / 100)
        color = "#4CAF50" if tax > 0 else "grey"
        self.lbl_cost_inc = QLabel(f"<b style='color:{color}'>${inc:.2f}</b>")
        self.lbl_cost_inc.setTextFormat(Qt.TextFormat.RichText)
        right_col.addLayout(info_row("Cost Price (inc GST)", self.lbl_cost_inc))

        r, self.lbl_sell = ro_row("Sell Price (inc GST)", f"${self._sell_price:.2f}", self._edit_sell)
        right_col.addLayout(r)

        self.lbl_gp = QLabel()
        self.lbl_gp.setTextFormat(Qt.TextFormat.RichText)
        self._refresh_gp()
        right_col.addLayout(info_row("Gross Profit", self.lbl_gp))

        r, self.lbl_tax = ro_row("Tax Rate", self._tax_label(), self._edit_tax)
        right_col.addLayout(r)

        r, self.lbl_reorder_pt = ro_row("Reorder Point", int(self._reorder_point), self._edit_reorder_point)
        right_col.addLayout(r)

        r, self.lbl_reorder_max = ro_row("Reorder Max", int(self._reorder_max), self._edit_reorder_max)
        right_col.addLayout(r)

        r, self.lbl_vw = ro_row("Variable Weight", "Yes" if self._variable_wt else "No", self._edit_variable_wt)
        right_col.addLayout(r)

        r, self.lbl_stocktake = ro_row("In Stocktake", "Yes" if self._in_stocktake else "No", self._edit_stocktake)
        right_col.addLayout(r)

        r, self.lbl_active = ro_row("Active", "Yes" if self._active else "No", self._edit_active)
        right_col.addLayout(r)

        r, self.lbl_auto_reorder = ro_row("On Reorder", "Yes" if self._auto_reorder else "No", self._edit_auto_reorder)
        right_col.addLayout(r)

        from models.stock_on_hand import get_by_barcode as _get_soh
        soh = _get_soh(self.barcode)
        soh_qty = int(soh["quantity"]) if soh else 0
        soh_color = "#4CAF50" if soh_qty > 0 else "#FF9800" if soh_qty == 0 else "#f44336"
        self.lbl_soh = QLabel(f'<span style="color:{soh_color};font-weight:bold;">{soh_qty}</span>')
        self.lbl_soh.setTextFormat(Qt.TextFormat.RichText)
        right_col.addLayout(info_row("Stock on Hand", self.lbl_soh))

        on_order = product_controller.get_stock_on_order(self.barcode)
        on_order_color = "#2196F3" if on_order > 0 else "#8b949e"
        self.lbl_on_order = QLabel(f'<span style="color:{on_order_color};font-weight:bold;">{on_order}</span>')
        self.lbl_on_order.setTextFormat(Qt.TextFormat.RichText)
        right_col.addLayout(info_row("Stock on Order", self.lbl_on_order))

        right_col.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("color: #2a3a4a;")

        two_col.addLayout(left_col, 1)
        two_col.addWidget(sep)
        two_col.addLayout(right_col, 1)
        layout.addLayout(two_col)

        # ── Bottom row: image + alternate barcodes ────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        img_group = QGroupBox("Product Image")
        img_lay = QHBoxLayout(img_group)
        img_lay.setSpacing(12)

        self._img_label = QLabel()
        self._img_label.setFixedSize(80, 80)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet(
            "background:#1a2332; border:1px solid #2a3a4a; border-radius:6px; color:#8b949e;"
        )
        img_lay.addWidget(self._img_label)

        img_btn_col = QVBoxLayout()
        img_btn_col.setSpacing(4)
        self._img_path_lbl = QLabel("No image")
        self._img_path_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        self._img_path_lbl.setWordWrap(True)
        img_btn_col.addWidget(self._img_path_lbl)
        btn_upload = QPushButton("📷  Upload Image")
        btn_upload.setFixedHeight(26)
        btn_upload.clicked.connect(self._upload_image)
        img_btn_col.addWidget(btn_upload)
        btn_remove = QPushButton("✕  Remove Image")
        btn_remove.setFixedHeight(26)
        btn_remove.clicked.connect(self._remove_image)
        img_btn_col.addWidget(btn_remove)
        img_btn_col.addStretch()
        img_lay.addLayout(img_btn_col)

        bottom_row.addWidget(img_group)
        self._load_image_preview()

        alias_group = QGroupBox("Alternate Barcodes")
        alias_layout = QVBoxLayout(alias_group)
        self.alias_table = QTableWidget()
        self.alias_table.setColumnCount(3)
        self.alias_table.setHorizontalHeaderLabels(["Barcode", "Note", "Added"])
        self.alias_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.alias_table.setMinimumHeight(60)
        self.alias_table.setMaximumHeight(100)
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

        bottom_row.addWidget(alias_group, 1)
        self._load_aliases()

        layout.addLayout(bottom_row)

        # ── Selling Units ─────────────────────────────────────────────
        layout.addWidget(self._build_selling_units_section())

        # ── Action buttons ────────────────────────────────────────────
        act_row = QHBoxLayout()
        btn_history = QPushButton("📋 View Movement History")
        btn_history.setFixedHeight(30)
        btn_history.clicked.connect(self._view_history)
        act_row.addWidget(btn_history)
        act_row.addStretch()
        save_btn = QPushButton("Save  [Ctrl+S]")
        save_btn.setFixedHeight(35)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        act_row.addWidget(save_btn)
        act_row.addWidget(cancel_btn)
        layout.addLayout(act_row)

    # ── Supplier SKU display ──────────────────────────────────────────

    def _supplier_sku_display(self):
        default = next((e for e in self._product_suppliers if e['is_default']), None)
        if not default:
            return "—"
        sku = default.get('supplier_sku') or "—"
        qty = default.get('pack_qty') or 1
        unit = default.get('pack_unit') or 'EA'
        if qty > 1:
            return f"{sku}  ({qty} × {unit} per carton)"
        return sku

    # ── Edit popup helpers ────────────────────────────────────────────

    def _edit_barcode(self):
        if self._selling_unit_guard(): return
        new_bc = _text_popup("Edit Barcode", "Barcode", self.product['barcode'], self)
        if new_bc is None or new_bc == self.product['barcode']:
            return
        try:
            product_controller.rename_barcode(self.barcode, new_bc)
            self.barcode = new_bc
            self.lbl_barcode.setText(new_bc)
            QMessageBox.information(self, "Updated", "Barcode updated to " + repr(new_bc))
        except ValueError as e:
            QMessageBox.warning(self, "Barcode Exists", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _edit_description(self):
        if self._selling_unit_guard(): return
        val = _text_popup("Edit Description", "Description", self._description, self)
        if val is not None:
            self._description = val
            self.lbl_desc.setText(val)

    def _edit_brand(self):
        val = _text_popup_optional("Edit Brand", "Brand", self._brand, self)
        if val is not None:
            self._brand = val
            self.lbl_brand.setText(val or "—")

    def _edit_plu(self):
        if self._selling_unit_guard(): return
        val = _text_popup_optional("Edit PLU", "PLU", self._plu, self)
        if val is not None:
            self._plu = val
            self.lbl_plu.setText(val or "—")

    def _edit_supplier_sku(self):
        self._edit_supplier()

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

    def _load_product_suppliers(self):
        return product_controller.get_product_suppliers(
            self.barcode,
            fallback_supplier_id=self._supplier_id,
            fallback_sku=self._supplier_sku,
            fallback_pack_qty=self._pack_qty,
            fallback_pack_unit=self._pack_unit,
        )

    def _edit_supplier(self):
        from PyQt6.QtWidgets import (
            QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
            QComboBox, QHBoxLayout, QVBoxLayout
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("Manage Suppliers")
        dlg.setMinimumWidth(740)
        dlg.setMinimumHeight(320)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        note = QLabel(
            "The Default supplier determines which purchase orders this product appears in. "
            "Set the Supplier SKU and carton pack size per supplier."
        )
        note.setStyleSheet("color: #8b949e; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._sup_table = QTableWidget()
        self._sup_table.setColumnCount(6)
        self._sup_table.setHorizontalHeaderLabels(
            ["Supplier", "Supplier SKU", "Pack Qty", "Unit", "Default", ""]
        )
        self._sup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._sup_table.setColumnWidth(1, 150)
        self._sup_table.setColumnWidth(2, 75)
        self._sup_table.setColumnWidth(3, 65)
        self._sup_table.setColumnWidth(4, 110)
        self._sup_table.setColumnWidth(5, 50)
        self._sup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._sup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._sup_table.verticalHeader().setVisible(False)
        self._sup_table.setAlternatingRowColors(True)
        self._sup_table.setMinimumHeight(120)
        layout.addWidget(self._sup_table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add Supplier")
        btn_add.setFixedHeight(30)
        btn_add.clicked.connect(self._add_supplier_popup)
        btn_row.addWidget(btn_add)
        btn_row.addStretch()
        btn_done = QPushButton("Done")
        btn_done.setFixedHeight(32)
        btn_done.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border: none; "
            "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
            "QPushButton:hover { background: #1976d2; }"
        )
        btn_done.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_done)
        layout.addLayout(btn_row)

        self._refresh_sup_table()
        dlg.exec()
        self.lbl_supplier.setText(self._supplier_name())
        self.lbl_supplier_sku.setText(self._supplier_sku_display())

    def _refresh_sup_table(self):
        self._sup_table.setUpdatesEnabled(False)
        self._sup_table.setRowCount(len(self._product_suppliers))
        for r, entry in enumerate(self._product_suppliers):
            self._sup_table.setItem(r, 0, QTableWidgetItem(entry['supplier_name']))

            # Col 1 — Supplier SKU (inline QLineEdit)
            sku_edit = QLineEdit(entry.get('supplier_sku') or '')
            sku_edit.setPlaceholderText("e.g. BIP-240")
            sku_edit.textChanged.connect(
                lambda text, i=r: self._product_suppliers[i].__setitem__('supplier_sku', text.strip())
            )
            self._sup_table.setCellWidget(r, 1, sku_edit)

            # Col 2 — Pack Qty (inline QSpinBox)
            qty_spin = QSpinBox()
            qty_spin.setMinimum(1)
            qty_spin.setMaximum(9999)
            qty_spin.setValue(entry.get('pack_qty') or 1)
            qty_spin.valueChanged.connect(
                lambda val, i=r: self._product_suppliers[i].__setitem__('pack_qty', val)
            )
            self._sup_table.setCellWidget(r, 2, qty_spin)

            # Col 3 — Pack Unit (inline QComboBox)
            unit_cb = QComboBox()
            unit_cb.addItems(['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML'])
            unit_cb.setCurrentText(entry.get('pack_unit') or 'EA')
            unit_cb.currentTextChanged.connect(
                lambda text, i=r: self._product_suppliers[i].__setitem__('pack_unit', text)
            )
            self._sup_table.setCellWidget(r, 3, unit_cb)

            # Col 4 — Default toggle
            if entry['is_default']:
                btn_def = QPushButton("★ Default")
                btn_def.setEnabled(False)
                btn_def.setFixedHeight(26)
                btn_def.setStyleSheet(
                    "QPushButton { background: #1565c0; color: white; border: none; "
                    "border-radius: 3px; font-weight: bold; }"
                )
            else:
                btn_def = QPushButton("Set Default")
                btn_def.setFixedHeight(26)
                btn_def.clicked.connect(lambda _, i=r: self._set_default_supplier(i))
            self._sup_table.setCellWidget(r, 4, btn_def)

            # Col 5 — Remove
            btn_rem = QPushButton("✕")
            btn_rem.setFixedHeight(26)
            btn_rem.setStyleSheet("color: #f44336; font-weight: bold;")
            btn_rem.clicked.connect(lambda _, i=r: self._remove_supplier(i))
            self._sup_table.setCellWidget(r, 5, btn_rem)

        self._sup_table.setUpdatesEnabled(True)

    def _add_supplier_popup(self):
        from PyQt6.QtWidgets import QFormLayout
        from PyQt6.QtGui import QShortcut, QKeySequence

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
        unit_cb.addItems(['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML'])
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
            "QPushButton { background: #1565c0; color: white; border: none; "
            "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
            "QPushButton:hover { background: #1976d2; }"
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
            self._refresh_sup_table()
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
        self._refresh_sup_table()

    def _set_default_supplier(self, idx):
        for i, entry in enumerate(self._product_suppliers):
            entry['is_default'] = (i == idx)
        self._refresh_sup_table()

    def _edit_unit(self):
        units = ['EA', 'KG', 'L', 'PK', 'CTN', 'G', 'ML']
        val = _choice_popup("Edit Unit", "Unit", units, self._unit, self)
        if val is not None:
            self._unit = val
            self.lbl_unit.setText(val)

    def _edit_sell(self):
        if self._selling_unit_guard(): return
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

    def _edit_auto_reorder(self):
        val = _choice_popup("On Reorder", "Always include on next PO for this supplier?",
                            ["No", "Yes"],
                            "Yes" if self._auto_reorder else "No", self)
        if val is not None:
            self._auto_reorder = (val == "Yes")
            self.lbl_auto_reorder.setText(val)

    # ── Helpers ───────────────────────────────────────────────────────

    def _dept_name(self):
        for d in self._depts:
            if d['id'] == self._dept_id:
                return d['name']
        return "Unknown"

    def _supplier_name(self):
        for entry in self._product_suppliers:
            if entry['is_default']:
                return entry['supplier_name']
        return "-- None --"

    def _tax_label(self):
        return "GST (10%)" if self._tax_rate == 10.0 else "GST Free (0%)"

    def _refresh_gp(self):
        sell = self._sell_price
        tax = self._tax_rate or 0.0
        cost = self._cost_price * (1 + tax / 100)
        if sell > 0:
            gp = (1 - cost / sell) * 100
            color = "green" if gp >= 30 else "orange" if gp >= 15 else "red"
            self.lbl_gp.setText(f"<b style='color:{color}'>{gp:.1f}%</b>")
        else:
            self.lbl_gp.setText("<b style='color:grey'>--</b>")

    # ── Image helpers ─────────────────────────────────────────────────

    def _image_path(self):
        from config.settings import DATA_DIR
        img_dir = os.path.join(DATA_DIR, 'images')
        for ext in ('jpg', 'jpeg', 'png', 'webp'):
            p = os.path.join(img_dir, f"{self.barcode}.{ext}")
            if os.path.exists(p):
                return p
        return None

    def _load_image_preview(self):
        path = self._image_path()
        if path:
            pix = QPixmap(path).scaled(
                80, 80,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._img_label.setPixmap(pix)
            self._img_path_lbl.setText(os.path.basename(path))
        else:
            self._img_label.setText("No image")
            self._img_label.setPixmap(QPixmap())
            self._img_path_lbl.setText("No image")

    def _upload_image(self):
        from config.settings import DATA_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Product Image",
            os.path.expanduser("~"),
            "Images (*.jpg *.jpeg *.png *.webp *.bmp);;All Files (*)"
        )
        if not path:
            return
        img_dir = os.path.join(DATA_DIR, 'images')
        os.makedirs(img_dir, exist_ok=True)
        # Save scaled copy as JPEG to keep file sizes manageable
        pix = QPixmap(path)
        if pix.isNull():
            QMessageBox.warning(self, "Invalid Image", "Could not load the selected file.")
            return
        pix = pix.scaled(
            600, 600,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        dest = os.path.join(img_dir, f"{self.barcode}.jpg")
        # Remove any existing alternate-extension copies first
        for ext in ('jpeg', 'png', 'webp', 'bmp'):
            old = os.path.join(img_dir, f"{self.barcode}.{ext}")
            if os.path.exists(old):
                os.remove(old)
        pix.save(dest, "JPEG", 88)
        self._load_image_preview()

    def _remove_image(self):
        path = self._image_path()
        if not path:
            return
        if QMessageBox.question(
            self, "Remove Image",
            "Remove the product image?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            os.remove(path)
            self._load_image_preview()

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

    # ── Selling Units ─────────────────────────────────────────────────

    def _build_selling_units_section(self) -> 'QGroupBox':
        from database.connection import get_connection as _gc
        grp = QGroupBox("Selling Units  (case, 6-pack, etc.)")
        lay = QVBoxLayout(grp)
        lay.setSpacing(6)

        note = QLabel(
            "Define alternate pack sizes that draw from this product's base stock. "
            "Each unit sold deducts the configured quantity from stock on hand."
        )
        note.setStyleSheet("color: #8b949e; font-size: 11px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        self._su_table = QTableWidget()
        self._su_table.setColumnCount(7)
        self._su_table.setHorizontalHeaderLabels(
            ["Barcode", "PLU", "Name", "Units / Pack", "Sell Price", "", ""]
        )
        self._su_table.setColumnWidth(0, 130)
        self._su_table.setColumnWidth(1, 70)
        self._su_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._su_table.setColumnWidth(3, 90)
        self._su_table.setColumnWidth(4, 90)
        self._su_table.setColumnWidth(5, 36)
        self._su_table.setColumnWidth(6, 36)
        self._su_table.setMaximumHeight(150)
        self._su_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._su_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._su_table.verticalHeader().setVisible(False)
        lay.addWidget(self._su_table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add Selling Unit")
        btn_add.setFixedHeight(28)
        btn_add.clicked.connect(self._add_selling_unit_popup)
        btn_row.addWidget(btn_add)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._load_selling_units()
        return grp

    def _load_selling_units(self):
        from database.connection import get_connection as _gc
        conn = _gc()
        try:
            rows = conn.execute(
                "SELECT id, label, unit_qty, plu, barcode, sell_price "
                "FROM product_selling_units WHERE master_barcode=? ORDER BY unit_qty",
                (self.barcode,)
            ).fetchall()
        finally:
            conn.close()

        self._su_table.setRowCount(0)
        for su in rows:
            r = self._su_table.rowCount()
            self._su_table.insertRow(r)

            bc_item = QTableWidgetItem(su['barcode'] or '—')
            bc_item.setData(Qt.ItemDataRole.UserRole, su['id'])
            self._su_table.setItem(r, 0, bc_item)

            plu_item = QTableWidgetItem(su['plu'] or '—')
            plu_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._su_table.setItem(r, 1, plu_item)

            self._su_table.setItem(r, 2, QTableWidgetItem(su['label']))

            qty_item = QTableWidgetItem(f"×{int(su['unit_qty']) if su['unit_qty'] == int(su['unit_qty']) else su['unit_qty']}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._su_table.setItem(r, 3, qty_item)

            price_item = QTableWidgetItem(f"${su['sell_price']:.2f}")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._su_table.setItem(r, 4, price_item)

            btn_edit = QPushButton("✎")
            btn_edit.setFixedHeight(24)
            btn_edit.setStyleSheet("color: #4fc3f7; font-weight: bold; border: none; background: transparent;")
            btn_edit.clicked.connect(lambda _, sid=su['id']: self._edit_selling_unit_popup(sid))
            self._su_table.setCellWidget(r, 5, btn_edit)

            btn_rem = QPushButton("✕")
            btn_rem.setFixedHeight(24)
            btn_rem.setStyleSheet("color: #f44336; font-weight: bold; border: none; background: transparent;")
            btn_rem.clicked.connect(lambda _, sid=su['id']: self._remove_selling_unit(sid))
            self._su_table.setCellWidget(r, 6, btn_rem)

    def _add_selling_unit_popup(self):
        from PyQt6.QtGui import QShortcut, QKeySequence
        from database.connection import get_connection as _gc

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
        price_spin.setPrefix("$")
        price_spin.setValue(round(self._sell_price * 6, 2))
        form.addRow("Sell Price *", price_spin)

        lay.addLayout(form)
        lay.addSpacing(4)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("Add  [Ctrl+S]")
        ok_btn.setFixedHeight(32)
        ok_btn.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border: none; "
            "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
            "QPushButton:hover { background: #1976d2; }"
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
            conn = _gc()
            try:
                plu_val = plu_input.text().strip() or None
                conn.execute(
                    "INSERT INTO product_selling_units "
                    "(master_barcode, barcode, plu, label, unit_qty, sell_price) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (self.barcode, barcode_val, plu_val, label, qty_spin.value(), price_spin.value())
                )
                conn.commit()
            except Exception as e:
                QMessageBox.critical(dlg, "Error", str(e))
                return
            finally:
                conn.close()
            self._load_selling_units()
            dlg.accept()

        ok_btn.clicked.connect(confirm)
        cancel_btn.clicked.connect(dlg.reject)
        QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
        QShortcut(QKeySequence("Escape"), dlg, dlg.reject)

        # Pre-fill price hint when qty changes
        qty_spin.valueChanged.connect(
            lambda v: price_spin.setValue(round(self._sell_price * v, 2))
        )

        lbl_input.setFocus()
        dlg.exec()

    def _edit_selling_unit_popup(self, su_id: int):
        from PyQt6.QtGui import QShortcut, QKeySequence
        from database.connection import get_connection as _gc

        conn = _gc()
        try:
            su = conn.execute(
                "SELECT id, label, unit_qty, plu, barcode, sell_price "
                "FROM product_selling_units WHERE id=?", (su_id,)
            ).fetchone()
        finally:
            conn.close()
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
        price_spin.setPrefix("$")
        price_spin.setValue(su['sell_price'])
        form.addRow("Sell Price *", price_spin)

        lay.addLayout(form)
        lay.addSpacing(4)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("Save  [Ctrl+S]")
        ok_btn.setFixedHeight(32)
        ok_btn.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border: none; "
            "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
            "QPushButton:hover { background: #1976d2; }"
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
            conn2 = _gc()
            try:
                conn2.execute(
                    "UPDATE product_selling_units "
                    "SET label=?, unit_qty=?, plu=?, barcode=?, sell_price=? WHERE id=?",
                    (label, qty_spin.value(), plu_val, barcode_val, price_spin.value(), su_id)
                )
                conn2.commit()
            except Exception as e:
                QMessageBox.critical(dlg, "Error", str(e))
                return
            finally:
                conn2.close()
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
        from database.connection import get_connection as _gc
        conn = _gc()
        try:
            conn.execute("DELETE FROM product_selling_units WHERE id = ?", (su_id,))
            conn.commit()
        finally:
            conn.close()
        self._load_selling_units()

    def _view_history(self):
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
            QTableWidgetItem, QHeaderView, QLabel, QComboBox, QPushButton
        )
        from PyQt6.QtGui import QShortcut, QKeySequence

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Movement History — {self.product['barcode']}")
        dlg.setMinimumSize(820, 500)
        layout = QVBoxLayout(dlg)

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

        tbl = QTableWidget()
        tbl.setColumnCount(6)
        tbl.setHorizontalHeaderLabels(["Date/Time", "Type", "Qty", "Balance", "Reference", "Notes"])
        hdr = tbl.horizontalHeader()
        for ci in range(5):
            hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
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
            rows = product_controller.get_movement_history(self.barcode, move_type)
            tbl.setRowCount(0)
            balance = 0.0
            display_rows = []
            for row in rows:
                balance += row["quantity"]
                display_rows.append((row, balance))

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

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close  [Esc]")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        QShortcut(QKeySequence("Escape"), dlg, dlg.accept)
        dlg.exec()

    def _save(self):
        default_sup = next((s for s in self._product_suppliers if s['is_default']), None)
        self._supplier_id = default_sup['supplier_id'] if default_sup else None
        # Sync products table from default supplier's per-supplier values
        supplier_sku = default_sup.get('supplier_sku', '') if default_sup else ''
        pack_qty     = default_sup.get('pack_qty', 1)     if default_sup else 1
        pack_unit    = default_sup.get('pack_unit', 'EA') if default_sup else 'EA'
        try:
            product_controller.save_product(
                barcode=self.barcode,
                description=self._description,
                brand=self._brand,
                plu=self._plu,
                supplier_sku=supplier_sku,
                pack_qty=pack_qty,
                pack_unit=pack_unit,
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
                auto_reorder=int(self._auto_reorder),
                product_suppliers=self._product_suppliers,
            )
            if self.on_save:
                self.on_save()
            self.close()
        except ValueError as e:
            QMessageBox.warning(self, "Validation", str(e))
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
    inp.setDecimals(4)
    inp.setValue(float(current))
    price_row = QHBoxLayout()
    price_row.addWidget(QLabel("$"))
    price_row.addWidget(inp)
    form.addRow(label, price_row)
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
