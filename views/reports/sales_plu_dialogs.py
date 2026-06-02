"""PLU-mapping dialogs and helpers extracted from sales_report_view.py.

Contains:
  - DB helpers (delegates to sales_report_controller)
  - _fuzzy_score / _plu_score (matching utilities)
  - _AddProductDialog (add a new product from a sales row)
  - _MatchItemDialog (right-click → Match Item)
"""
import re as _re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QHeaderView, QComboBox, QDialog, QLineEdit,
    QAbstractItemView, QFormLayout, QDoubleSpinBox, QSpinBox,
    QCheckBox, QTextEdit, QFrame, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut

import config.styles as styles
import controllers.sales_report_controller as sales_ctrl
from utils.error_dialog import show_error
from views.widgets.table_items import item as _item, RIGHT, CENTER
from views.widgets.table_utils import make_table as _make_table


# ── DB helpers — thin delegates to sales_report_controller ───────────────────

def _ensure_plu_map_table():   sales_ctrl.ensure_plu_map_table()
def _save_plu_map(plu, bc):    sales_ctrl.save_plu_map(plu, bc)
def _backfill_sale_movements(plu, bc): sales_ctrl.backfill_sale_movements(plu, bc)
def _load_plu_map():           return sales_ctrl.load_plu_map()
def _get_departments():        return sales_ctrl.get_departments()
def _get_suppliers():          return sales_ctrl.get_suppliers()
def _barcode_exists(bc):       return sales_ctrl.barcode_exists(bc)
def _get_all_products():       return sales_ctrl.get_all_products()


# ── Matching utilities ────────────────────────────────────────────────────────

def _fuzzy_score(query: str, candidate: str) -> int:
    if not query or not candidate:
        return 0
    q, c = query.lower().strip(), candidate.lower().strip()
    if q == c:   return 100
    if c.startswith(q[:min(len(q), 8)]): return 85
    if q in c or c in q: return 75
    qt = set(_re.sub(r"[^a-z0-9 ]", "", q).split())
    ct = set(_re.sub(r"[^a-z0-9 ]", "", c).split())
    if not qt: return 0
    return int(len(qt & ct) / max(len(qt), len(ct)) * 65)


def _plu_score(sales_plu, product_plu) -> int:
    """Return 100 if PLUs match exactly, else 0."""
    try:
        return 100 if int(str(sales_plu).strip()) == int(str(product_plu).strip()) else 0
    except (ValueError, TypeError):
        return 0


# ── Add Product dialog ────────────────────────────────────────────────────────

class _AddProductDialog(QDialog):
    def __init__(self, prefill: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Product")
        self.setMinimumWidth(500)
        self.setModal(True)
        self.saved_barcode = None
        self._depts     = _get_departments()
        self._suppliers = _get_suppliers()
        self._build(prefill)

    def _build(self, pf):
        root = QVBoxLayout(self)
        root.setSpacing(4)

        title = QLabel("Add Product")
        title.setStyleSheet("font-size:15px; font-weight:700; padding:6px 0 4px 0;")
        root.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#333;"); root.addWidget(sep)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        fw = QWidget()
        form = QFormLayout(fw); form.setSpacing(7)
        form.setContentsMargins(4, 8, 4, 8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scroll.setWidget(fw); root.addWidget(scroll)

        def req(t): l=QLabel(f"{t} *"); l.setStyleSheet(f"color:{styles.CLR_TEXT};"); return l
        def opt(t): l=QLabel(t); l.setStyleSheet(f"color:{styles.CLR_MUTED};"); return l

        self.f_barcode = QLineEdit(pf.get("barcode",""))
        self.f_barcode.setPlaceholderText("Scan or type barcode")
        form.addRow(req("Barcode"), self.f_barcode)

        self.f_desc = QLineEdit(pf.get("description",""))
        self.f_desc.setPlaceholderText("Product description")
        form.addRow(req("Description"), self.f_desc)

        self.f_brand = QLineEdit(pf.get("brand",""))
        self.f_brand.setPlaceholderText("Brand name (optional)")
        form.addRow(opt("Brand"), self.f_brand)

        self.f_plu = QLineEdit(pf.get("plu",""))
        self.f_plu.setPlaceholderText("PLU number (optional)")
        form.addRow(opt("PLU"), self.f_plu)
        self.f_sku = QLineEdit(pf.get("base_sku",""))
        self.f_sku.setPlaceholderText("Internal SKU (optional)")
        form.addRow(opt("SKU"), self.f_sku)

        self.f_supplier = QComboBox()
        self.f_supplier.addItem("— None —", None)
        for s in self._suppliers:
            self.f_supplier.addItem(s["name"], s["id"])
        form.addRow(opt("Supplier"), self.f_supplier)

        upc_w = QWidget(); upc_lay = QHBoxLayout(upc_w)
        upc_lay.setContentsMargins(0,0,0,0); upc_lay.setSpacing(6)
        self.f_upc = QSpinBox(); self.f_upc.setRange(0,9999); self.f_upc.setValue(1)
        self.f_unit_type = QComboBox()
        for u in ["EA","KG","G","L","ML","PK","CTN","DOZ"]:
            self.f_unit_type.addItem(u)
        self.f_unit_type.setCurrentText(pf.get("unit","EA"))
        upc_lay.addWidget(self.f_upc); upc_lay.addWidget(QLabel("×"))
        upc_lay.addWidget(self.f_unit_type); upc_lay.addWidget(QLabel("per carton"))
        upc_lay.addStretch()
        form.addRow(opt("Units/Carton"), upc_w)

        self.f_dept = QComboBox()
        for d in self._depts:
            self.f_dept.addItem(d["name"], d["id"])
        pref_dept = pf.get("dept_name","")
        for i in range(self.f_dept.count()):
            if self.f_dept.itemText(i).lower() == pref_dept.lower():
                self.f_dept.setCurrentIndex(i); break
        form.addRow(req("Department"), self.f_dept)

        self.f_unit_size = QLineEdit(pf.get("unit_size",""))
        self.f_unit_size.setPlaceholderText("e.g. 500g, 1L")
        form.addRow(opt("Unit Size"), self.f_unit_size)

        self.f_cost = QDoubleSpinBox(); self.f_cost.setRange(0,99999)
        self.f_cost.setDecimals(2); self.f_cost.setPrefix("$")
        self.f_cost.setValue(float(pf.get("cost_price") or 0))
        form.addRow(opt("Cost Price"), self.f_cost)

        self.f_sell = QDoubleSpinBox(); self.f_sell.setRange(0,99999)
        self.f_sell.setDecimals(2); self.f_sell.setPrefix("$")
        self.f_sell.setValue(float(pf.get("sell_price") or 0))
        form.addRow(opt("Sell Price"), self.f_sell)

        self.f_gp = QLabel("—"); self.f_gp.setStyleSheet(f"color:{styles.CLR_SUCCESS};")
        self.f_cost.valueChanged.connect(self._update_gp)
        self.f_sell.valueChanged.connect(self._update_gp)
        self._update_gp()
        form.addRow(opt("Gross Profit"), self.f_gp)

        self.f_tax = QComboBox()
        for t in ["GST (10%)","GST Free (0%)","Wine (29%)"]:
            self.f_tax.addItem(t)
        form.addRow(opt("Tax Rate"), self.f_tax)

        self.f_rp = QDoubleSpinBox(); self.f_rp.setRange(0,9999)
        self.f_rq = QDoubleSpinBox(); self.f_rq.setRange(0,9999)
        form.addRow(opt("Reorder Point"), self.f_rp)
        form.addRow(opt("Reorder Qty"),   self.f_rq)

        self.f_varweight = QCheckBox("Variable weight item (deli/meat)")
        self.f_stocktake = QCheckBox("Include in stocktake")
        self.f_stocktake.setChecked(True)
        form.addRow(QLabel(), self.f_varweight)
        form.addRow(QLabel(), self.f_stocktake)

        self.f_notes = QTextEdit(); self.f_notes.setFixedHeight(52)
        self.f_notes.setPlaceholderText("Notes (optional)")
        form.addRow(opt("Notes"), self.f_notes)

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("Save  [Ctrl+S]")
        self.btn_save.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:6px 18px;font-weight:700;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}")
        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_row.addWidget(self.btn_save); btn_row.addWidget(btn_cancel)
        btn_row.addStretch(); root.addLayout(btn_row)

        self.btn_save.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._save)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.reject)
        self.f_barcode.setFocus()

    def _update_gp(self):
        sp, cp = self.f_sell.value(), self.f_cost.value()
        if sp > 0:
            pct = (sp-cp)/sp*100; dol = sp-cp
            col = styles.CLR_SUCCESS if dol >= 0 else styles.CLR_DANGER
            self.f_gp.setStyleSheet(f"color:{col};")
            self.f_gp.setText(f"{pct:.1f}%  (${dol:.2f})")
        else:
            self.f_gp.setText("—")

    def _save(self):
        import controllers.product_controller as product_ctrl
        barcode = self.f_barcode.text().strip()
        desc    = self.f_desc.text().strip()
        if not barcode:
            QMessageBox.warning(self, "Required", "Barcode is required.")
            self.f_barcode.setFocus(); return
        if not desc:
            QMessageBox.warning(self, "Required", "Description is required.")
            self.f_desc.setFocus(); return
        if not self.f_dept.currentData():
            QMessageBox.warning(self, "Required", "Department is required."); return

        if _barcode_exists(barcode):
            ans = QMessageBox.question(
                self, "Barcode Exists",
                f"Barcode {barcode!r} already exists.\n"
                "Update that product instead?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.No: return

        tax_map = {"GST (10%)":10.0,"GST Free (0%)":0.0,"Wine (29%)":29.0}
        try:
            product_ctrl.add_product(
                barcode=barcode,
                description=desc,
                department_id=self.f_dept.currentData(),
                supplier_id=self.f_supplier.currentData(),
                brand=self.f_brand.text().strip(),
                base_sku=self.f_sku.text().strip(),
                unit=self.f_unit_type.currentText(),
                pack_qty=self.f_upc.value() or 1,
                sell_price=self.f_sell.value(),
                cost_price=self.f_cost.value(),
                tax_rate=tax_map.get(self.f_tax.currentText(), 10.0),
                reorder_point=self.f_rp.value(),
                reorder_max=0,
                variable_weight=int(self.f_varweight.isChecked()),
                expected=int(self.f_stocktake.isChecked()),
            )
            self.saved_barcode = barcode
            self.accept()
        except Exception as e:
            show_error(self, "Could not add product.", e)


# ── Match Item dialog ─────────────────────────────────────────────────────────

class _MatchItemDialog(QDialog):
    """Right-click → Match Item.

    Left panel : details of the selected sales row.
    Right panel: searchable list of all DB products with fuzzy scoring.
    Operator picks a match and clicks Assign, or clicks Add New Product.
    """

    def __init__(self, sales_row: dict, parent=None):
        super().__init__(parent)
        self.sales_row    = sales_row
        self.all_products = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_search)
        self.setWindowTitle("Match Item")
        self.setMinimumSize(1100, 680)
        self.resize(1200, 720)
        self.setModal(True)
        self._build_ui()
        self.all_products = _get_all_products()
        self._run_search()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        tb = QWidget(); tb.setStyleSheet(styles.STYLE_PANEL_HEADER)
        tb_lay = QHBoxLayout(tb); tb_lay.setContentsMargins(16,10,16,10)
        t = QLabel("Match Item"); t.setStyleSheet("font-size:15px;font-weight:700;")
        hint = QLabel("Select an existing product to link, or add as new")
        hint.setStyleSheet(styles.STYLE_LABEL_EXTRA_DIM)
        tb_lay.addWidget(t); tb_lay.addSpacing(12); tb_lay.addWidget(hint); tb_lay.addStretch()
        root.addWidget(tb)

        body = QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)
        root.addLayout(body, stretch=1)

        left = QWidget(); left.setFixedWidth(270)
        left.setStyleSheet(styles.STYLE_PANEL_SIDEBAR)
        ll = QVBoxLayout(left); ll.setContentsMargins(16,16,16,16); ll.setSpacing(10)
        ll.addWidget(self._sec_lbl("SALES ROW"))

        plu   = self.sales_row.get("plu","")
        name  = self.sales_row.get("plu_name","")
        bc    = self.sales_row.get("barcode","") or ""
        sg    = self.sales_row.get("sub_group","")
        sales = self.sales_row.get("total_sales", 0)
        qty   = self.sales_row.get("total_qty", 0)

        self._add_detail(ll, "PLU",         str(plu))
        self._add_detail(ll, "Barcode",     bc or "⚠ None",
                         color=styles.CLR_DANGER if not bc else "#58a6ff")
        self._add_detail(ll, "Name",        name)
        self._add_detail(ll, "Sub Group",   sg or "—")
        self._add_detail(ll, "Total Sales", f"${sales:,.2f}", color=styles.CLR_SUCCESS_ALT)
        self._add_detail(ll, "Total Qty",   str(int(qty)), color=styles.CLR_BLUE)
        ll.addStretch()

        self.btn_add_new = QPushButton("+ Add New Product")
        self.btn_add_new.setStyleSheet(
            f"QPushButton{{background:#1b3a2a;border:1px solid {styles.CLR_SUCCESS};color:{styles.CLR_SUCCESS};"
            "border-radius:4px;padding:7px 0;font-weight:700;font-size:12px;}"
            "QPushButton:hover{background:#2ea04333;}")
        self.btn_add_new.clicked.connect(self._add_new)
        ll.addWidget(self.btn_add_new)
        body.addWidget(left)

        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        sb = QWidget(); sb.setStyleSheet(f"background:{styles.CLR_BG};border-bottom:1px solid {styles.CLR_BORDER};")
        sb_lay = QHBoxLayout(sb); sb_lay.setContentsMargins(12,8,12,8); sb_lay.setSpacing(8)
        sb_lay.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Type name, barcode or brand…")
        self.search_edit.setText(self.sales_row.get("plu_name",""))
        self.search_edit.textChanged.connect(lambda _: self._timer.start(500))
        sb_lay.addWidget(self.search_edit, stretch=1)
        self.lbl_count = QLabel(""); self.lbl_count.setStyleSheet(styles.STYLE_LABEL_EXTRA_DIM)
        sb_lay.addWidget(self.lbl_count)
        rl.addWidget(sb)

        self.cand_table = _make_table(
            ["Score","PLU","Barcode","Description","Brand","Dept","Sell $","Cost $"],
            stretch_col=3
        )
        _ch = self.cand_table.horizontalHeader()
        for _ci in range(8):
            _ch.setSectionResizeMode(_ci, QHeaderView.ResizeMode.Interactive)
        _ch.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.cand_table.setColumnWidth(0, 52)
        self.cand_table.setColumnWidth(1, 55)
        self.cand_table.setColumnWidth(2, 130)
        self.cand_table.setColumnWidth(4, 120)
        self.cand_table.setColumnWidth(5, 110)
        self.cand_table.setColumnWidth(6, 80)
        self.cand_table.setColumnWidth(7, 80)
        self.cand_table.selectionModel().selectionChanged.connect(
            lambda: self.btn_assign.setEnabled(self._selected_product() is not None))
        self.cand_table.doubleClicked.connect(self._assign)
        rl.addWidget(self.cand_table, stretch=1)
        body.addWidget(right, stretch=1)

        ab = QWidget(); ab.setStyleSheet(styles.STYLE_PANEL_FOOTER)
        ab_lay = QHBoxLayout(ab); ab_lay.setContentsMargins(16,10,16,10); ab_lay.setSpacing(10)

        self.btn_assign = QPushButton("✓  Assign Match")
        self.btn_assign.setEnabled(False)
        self.btn_assign.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};border:1px solid {styles.CLR_ACCENT_HOVER};color:white;"
            "border-radius:4px;padding:7px 20px;font-weight:700;font-size:13px;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
            "QPushButton:disabled{opacity:0.4;}")
        self.btn_assign.clicked.connect(self._assign)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #444;color:#888;"
            "border-radius:4px;padding:7px 16px;}"
            f"QPushButton:hover{{border-color:#888;color:{styles.CLR_TEXT};}}")
        btn_cancel.clicked.connect(self.reject)

        hint2 = QLabel("Double-click a row to assign immediately")
        hint2.setStyleSheet(styles.STYLE_LABEL_EXTRA_DIM)
        ab_lay.addWidget(self.btn_assign); ab_lay.addWidget(btn_cancel)
        ab_lay.addSpacing(12); ab_lay.addWidget(hint2); ab_lay.addStretch()
        root.addWidget(ab)

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.reject)

    def _sec_lbl(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{styles.CLR_EXTRA_DIM};font-size:10px;letter-spacing:1.5px;")
        return l

    def _add_detail(self, layout, label, value, color=None):
        if color is None:
            color = styles.CLR_TEXT
        w = QWidget(); wl = QVBoxLayout(w); wl.setContentsMargins(0,0,0,0); wl.setSpacing(1)
        lbl = QLabel(label); lbl.setStyleSheet(f"color:{styles.CLR_EXTRA_DIM};font-size:10px;")
        val = QLabel(value); val.setWordWrap(True)
        val.setStyleSheet(f"color:{color};font-size:13px;font-weight:600;")
        wl.addWidget(lbl); wl.addWidget(val); layout.addWidget(w)

    def _run_search(self):
        query = self.search_edit.text().strip()
        if not query:
            self.cand_table.setRowCount(0); return

        sales_plu = self.sales_row.get("plu", "")
        scored = []
        for p in self.all_products:
            s = _fuzzy_score(query, p.get("description",""))
            if p.get("barcode","").lower().startswith(query.lower()) and query.isdigit():
                s = 98
            if query.lower() in (p.get("brand") or "").lower():
                s = max(s, 55)
            plu_s = _plu_score(sales_plu, p.get("plu",""))
            if plu_s == 100:
                s = 100
            if s > 12:
                scored.append((s, p))
        scored.sort(key=lambda x: -x[0])
        scored = scored[:50]

        self.cand_table.setSortingEnabled(False)
        self.cand_table.setRowCount(len(scored))
        for r, (score, p) in enumerate(scored):
            sc_item = _item(str(score), CENTER)
            sc_item.setForeground(QColor(
                styles.CLR_SUCCESS if score >= 70 else "#f0c040" if score >= 40 else styles.CLR_MUTED))
            desc_item = _item(p.get("description",""))
            desc_item.setData(Qt.ItemDataRole.UserRole, p)
            self.cand_table.setItem(r, 0, sc_item)
            self.cand_table.setItem(r, 1, _item(str(p.get("plu","") or "—"), CENTER))
            self.cand_table.setItem(r, 2, _item(p.get("barcode","")))
            self.cand_table.setItem(r, 3, desc_item)
            self.cand_table.setItem(r, 4, _item(p.get("brand") or "—"))
            self.cand_table.setItem(r, 5, _item(p.get("dept_name") or "—"))
            self.cand_table.setItem(r, 6, _item(f"${p.get('sell_price',0):.2f}", RIGHT))
            self.cand_table.setItem(r, 7, _item(f"${p.get('cost_price',0):.2f}", RIGHT))

        self.cand_table.setSortingEnabled(True)
        self.lbl_count.setText(f"{len(scored)} candidates")
        self.btn_assign.setEnabled(False)
        if scored:
            self.cand_table.selectRow(0)

    def _selected_product(self):
        row = self.cand_table.currentRow()
        if row < 0: return None
        item = self.cand_table.item(row, 3)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _assign(self):
        prod = self._selected_product()
        if not prod:
            QMessageBox.warning(self, "No Selection", "Select a product from the list.")
            return

        sales_bc    = (self.sales_row.get("barcode") or "").strip()
        existing_bc = prod.get("barcode","").strip()

        if sales_bc and sales_bc != existing_bc:
            if _barcode_exists(sales_bc):
                QMessageBox.warning(self, "Barcode Conflict",
                    f"Barcode {sales_bc!r} already belongs to another product.\n"
                    "Resolve this in the Products screen.")
                return
            ans = QMessageBox.question(self, "Update Barcode?",
                f"Update product:\n  {prod['description']}\n\n"
                f"  Current barcode: {existing_bc}\n"
                f"  New barcode:     {sales_bc}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes: return
            try:
                self._update_barcode(existing_bc, sales_bc)
            except Exception as e:
                show_error(self, "Could not update barcode.", e); return
            _save_plu_map(self.sales_row.get("plu"), sales_bc)
            QMessageBox.information(self, "Matched",
                f"✓ '{prod['description']}' barcode updated to {sales_bc}")
        else:
            _save_plu_map(self.sales_row.get("plu"), existing_bc)
            QMessageBox.information(self, "Matched",
                f"✓ Linked to:\n\n  {prod['description']}\n"
                f"  Barcode: {existing_bc}\n  Dept: {prod.get('dept_name','')}")
        self.accept()

    def _update_barcode(self, old_bc: str, new_bc: str):
        sales_ctrl.update_product_barcode(old_bc, new_bc)

    def _add_new(self):
        prefill = {
            "barcode":      self.sales_row.get("barcode",""),
            "description":  self.sales_row.get("plu_name",""),
            "dept_name":    self.sales_row.get("sub_group",""),
        }
        dlg = _AddProductDialog(prefill, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            _save_plu_map(self.sales_row.get("plu"), dlg.saved_barcode)
            QMessageBox.information(self, "Product Added",
                f"✓ New product saved:\n\n"
                f"  {dlg.f_desc.text()}\n  Barcode: {dlg.saved_barcode}")
            self.accept()
