from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDateEdit, QFileDialog, QMessageBox, QTabWidget, QFrame,
    QMenu, QDialog, QLineEdit, QAbstractItemView, QScrollArea,
    QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QTextEdit,
    QApplication,
)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor, QAction, QKeySequence, QShortcut
from database.connection import get_connection
import csv, os, subprocess, sys


# ─────────────────────────────────────────────────────────────────────────────
# Table helpers
# ─────────────────────────────────────────────────────────────────────────────
class NumItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text().replace('$','').replace(',','').replace('%','')) < \
                   float(other.text().replace('$','').replace(',','').replace('%',''))
        except ValueError:
            return self.text() < other.text()


def _item(text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, numeric=False):
    i = NumItem(str(text)) if numeric else QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    return i


RIGHT  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter


def _make_table(headers, stretch_col=1):
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setSortingEnabled(True)
    return t


def _stat_card(label, value, color="#2196F3"):
    frame = QFrame()
    frame.setStyleSheet(f"""
        QFrame {{
            background: #1e2a38;
            border-radius: 8px;
            border-left: 4px solid {color};
        }}
    """)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 12)
    val_lbl = QLabel(value)
    val_lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color};")
    lbl_lbl = QLabel(label)
    lbl_lbl.setStyleSheet("font-size: 11px; color: #aaa;")
    layout.addWidget(val_lbl)
    layout.addWidget(lbl_lbl)
    return frame, val_lbl, lbl_lbl


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_plu_map_table():
    """Create plu_barcode_map if it doesn't exist yet (safe to call every run)."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plu_barcode_map (
                plu     INTEGER PRIMARY KEY,
                barcode TEXT    NOT NULL,
                mapped_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _save_plu_map(plu, barcode: str):
    """Persist a PLU→barcode mapping so future PDF imports resolve automatically."""
    try:
        plu_int = int(str(plu).strip())
    except (ValueError, TypeError):
        return
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO plu_barcode_map (plu, barcode, mapped_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (plu_int, barcode)
        )
        conn.commit()
    finally:
        conn.close()
    # Backfill any historical sales movements now that PLU is mapped
    _backfill_sale_movements(plu, barcode)


def _backfill_sale_movements(plu, barcode: str):
    """
    After a PLU→barcode mapping is saved, retroactively create stock movements
    for any historical sales_daily records that were imported before the mapping
    existed.
    """
    try:
        plu_str = str(plu).strip()
        conn = get_connection()
        try:
            # Find all sales_daily rows for this PLU with no existing movement
            orphaned = conn.execute("""
                SELECT sd.sale_date, sd.plu, sd.plu_name, sd.quantity
                FROM sales_daily sd
                WHERE sd.plu = ?
                AND NOT EXISTS (
                    SELECT 1 FROM stock_movements sm
                    WHERE sm.barcode = ?
                    AND sm.reference = 'SALE-' || sd.sale_date || '-PLU' || sd.plu
                )
                ORDER BY sd.sale_date
            """, (plu_str, barcode)).fetchall()

            if not orphaned:
                return

            backfilled = 0
            for row in orphaned:
                reference = f"SALE-{row['sale_date']}-PLU{row['plu']}"
                quantity  = float(row['quantity'])
                plu_name  = row['plu_name'] or ""

                # Create movement
                conn.execute("""
                    INSERT INTO stock_movements
                        (barcode, movement_type, quantity, reference, notes, created_by)
                    VALUES (?, 'SALE', ?, ?, ?, 'PDF Import (backfill)')
                """, (barcode, -quantity, reference,
                      f"Backfill: {plu_name} ({quantity} units)"))

                # Update SOH — creates row if not exists
                conn.execute("""
                    INSERT INTO stock_on_hand (barcode, quantity)
                    VALUES (?, ?)
                    ON CONFLICT(barcode) DO UPDATE SET
                        quantity = quantity + excluded.quantity,
                        last_updated = CURRENT_TIMESTAMP
                """, (barcode, -quantity))

                backfilled += 1

            conn.commit()
            if backfilled:
                print(f"  Backfilled {backfilled} sale movements for PLU {plu} → {barcode}")
        finally:
            conn.close()
    except Exception as e:
        print(f"  Backfill error: {e}")


def _load_plu_map() -> dict:
    """Return {plu_int: barcode} from the persistent map table."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT plu, barcode FROM plu_barcode_map").fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def _get_departments():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name FROM departments WHERE active=1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _get_suppliers():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name FROM suppliers WHERE active=1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _barcode_exists(barcode: str) -> bool:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT 1 FROM products WHERE barcode=?", (barcode,)
        ).fetchone() is not None
    finally:
        conn.close()


def _get_all_products():
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.barcode, p.description, p.brand,
                   COALESCE(p.plu, '') as plu,
                   d.name as dept_name, d.id as dept_id,
                   s.name as supplier_name, s.id as supplier_id,
                   p.sell_price, p.cost_price, p.unit
            FROM products p
            LEFT JOIN departments d ON p.department_id = d.id
            LEFT JOIN suppliers   s ON p.supplier_id   = s.id
            WHERE p.active = 1
            ORDER BY p.description
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


import re as _re
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


# ─────────────────────────────────────────────────────────────────────────────
# Add Product dialog  (mirrors Products view form exactly)
# ─────────────────────────────────────────────────────────────────────────────
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

        def req(t): l=QLabel(f"{t} *"); l.setStyleSheet("color:#e6edf3;"); return l
        def opt(t): l=QLabel(t); l.setStyleSheet("color:#8b949e;"); return l

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

        self.f_gp = QLabel("—"); self.f_gp.setStyleSheet("color:#3fb950;")
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
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:6px 18px;font-weight:700;}"
            "QPushButton:hover{background:#1976d2;}")
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
            col = "#3fb950" if dol >= 0 else "#f85149"
            self.f_gp.setStyleSheet(f"color:{col};")
            self.f_gp.setText(f"{pct:.1f}%  (${dol:.2f})")
        else:
            self.f_gp.setText("—")

    def _save(self):
        import models.product as prod_model
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
            prod_model.add(
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
            QMessageBox.critical(self, "Database Error", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Match Item dialog
# ─────────────────────────────────────────────────────────────────────────────
class _MatchItemDialog(QDialog):
    """
    Right-click → Match Item.
    Left panel : details of the selected sales row.
    Right panel: searchable list of all DB products with fuzzy scoring.
    Operator picks a match and clicks Assign, or clicks Add New Product.
    """

    def __init__(self, sales_row: dict, parent=None):
        super().__init__(parent)
        self.sales_row   = sales_row
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

        # Title bar
        tb = QWidget(); tb.setStyleSheet("background:#1e2a38; border-bottom:1px solid #2a3a4a;")
        tb_lay = QHBoxLayout(tb); tb_lay.setContentsMargins(16,10,16,10)
        t = QLabel("Match Item"); t.setStyleSheet("font-size:15px;font-weight:700;")
        hint = QLabel("Select an existing product to link, or add as new")
        hint.setStyleSheet("color:#6e7681;font-size:11px;")
        tb_lay.addWidget(t); tb_lay.addSpacing(12); tb_lay.addWidget(hint); tb_lay.addStretch()
        root.addWidget(tb)

        # Body
        body = QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)
        root.addLayout(body, stretch=1)

        # LEFT: sales row details
        left = QWidget(); left.setFixedWidth(270)
        left.setStyleSheet("background:#1e2a38; border-right:1px solid #2a3a4a;")
        ll = QVBoxLayout(left); ll.setContentsMargins(16,16,16,16); ll.setSpacing(10)
        ll.addWidget(self._sec_lbl("SALES ROW"))

        plu    = self.sales_row.get("plu","")
        name   = self.sales_row.get("plu_name","")
        bc     = self.sales_row.get("barcode","") or ""
        sg     = self.sales_row.get("sub_group","")
        sales  = self.sales_row.get("total_sales", 0)
        qty    = self.sales_row.get("total_qty", 0)

        self._add_detail(ll, "PLU",         str(plu))
        self._add_detail(ll, "Barcode",     bc or "⚠ None",
                         color="#f85149" if not bc else "#58a6ff")
        self._add_detail(ll, "Name",        name)
        self._add_detail(ll, "Sub Group",   sg or "—")
        self._add_detail(ll, "Total Sales", f"${sales:,.2f}", color="#4CAF50")
        self._add_detail(ll, "Total Qty",   str(int(qty)), color="#2196F3")

        ll.addStretch()

        self.btn_add_new = QPushButton("+ Add New Product")
        self.btn_add_new.setStyleSheet(
            "QPushButton{background:#1b3a2a;border:1px solid #3fb950;color:#3fb950;"
            "border-radius:4px;padding:7px 0;font-weight:700;font-size:12px;}"
            "QPushButton:hover{background:#2ea04333;}")
        self.btn_add_new.clicked.connect(self._add_new)
        ll.addWidget(self.btn_add_new)
        body.addWidget(left)

        # RIGHT: search + candidates
        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        sb = QWidget(); sb.setStyleSheet("background:#1a2433;border-bottom:1px solid #2a3a4a;")
        sb_lay = QHBoxLayout(sb); sb_lay.setContentsMargins(12,8,12,8); sb_lay.setSpacing(8)
        sb_lay.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Type name, barcode or brand…")
        self.search_edit.setText(self.sales_row.get("plu_name",""))
        self.search_edit.textChanged.connect(lambda _: self._timer.start(500))
        sb_lay.addWidget(self.search_edit, stretch=1)
        self.lbl_count = QLabel(""); self.lbl_count.setStyleSheet("color:#6e7681;font-size:11px;")
        sb_lay.addWidget(self.lbl_count)
        rl.addWidget(sb)

        self.cand_table = _make_table(
            ["Score","PLU","Barcode","Description","Brand","Dept","Sell $","Cost $"],
            stretch_col=3
        )
        # All columns interactively resizable; Description stretches to fill
        _ch = self.cand_table.horizontalHeader()
        for _ci in range(8):
            _ch.setSectionResizeMode(_ci, QHeaderView.ResizeMode.Interactive)
        _ch.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.cand_table.setColumnWidth(0, 52)   # Score
        self.cand_table.setColumnWidth(1, 55)   # PLU
        self.cand_table.setColumnWidth(2, 130)  # Barcode
        # col 3 Description stretches
        self.cand_table.setColumnWidth(4, 120)  # Brand
        self.cand_table.setColumnWidth(5, 110)  # Dept
        self.cand_table.setColumnWidth(6, 80)   # Sell $
        self.cand_table.setColumnWidth(7, 80)   # Cost $
        self.cand_table.selectionModel().selectionChanged.connect(
            lambda: self.btn_assign.setEnabled(self._selected_product() is not None))
        self.cand_table.doubleClicked.connect(self._assign)
        rl.addWidget(self.cand_table, stretch=1)
        body.addWidget(right, stretch=1)

        # Action bar
        ab = QWidget(); ab.setStyleSheet("background:#1e2a38;border-top:1px solid #2a3a4a;")
        ab_lay = QHBoxLayout(ab); ab_lay.setContentsMargins(16,10,16,10); ab_lay.setSpacing(10)

        self.btn_assign = QPushButton("✓  Assign Match")
        self.btn_assign.setEnabled(False)
        self.btn_assign.setStyleSheet(
            "QPushButton{background:#1565c0;border:1px solid #1976d2;color:white;"
            "border-radius:4px;padding:7px 20px;font-weight:700;font-size:13px;}"
            "QPushButton:hover{background:#1976d2;}"
            "QPushButton:disabled{opacity:0.4;}")
        self.btn_assign.clicked.connect(self._assign)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #444;color:#888;"
            "border-radius:4px;padding:7px 16px;}"
            "QPushButton:hover{border-color:#888;color:#e6edf3;}")
        btn_cancel.clicked.connect(self.reject)

        hint2 = QLabel("Double-click a row to assign immediately")
        hint2.setStyleSheet("color:#6e7681;font-size:11px;")

        ab_lay.addWidget(self.btn_assign); ab_lay.addWidget(btn_cancel)
        ab_lay.addSpacing(12); ab_lay.addWidget(hint2); ab_lay.addStretch()
        root.addWidget(ab)

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.reject)

    def _sec_lbl(self, text):
        l = QLabel(text); l.setStyleSheet("color:#6e7681;font-size:10px;letter-spacing:1.5px;")
        return l

    def _add_detail(self, layout, label, value, color="#e6edf3"):
        w = QWidget(); wl = QVBoxLayout(w); wl.setContentsMargins(0,0,0,0); wl.setSpacing(1)
        lbl = QLabel(label); lbl.setStyleSheet("color:#6e7681;font-size:10px;")
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
            # Boost if product PLU matches sales PLU
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
                "#3fb950" if score>=70 else "#f0c040" if score>=40 else "#8b949e"))
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
                QMessageBox.critical(self, "Error", str(e)); return
            # Persist the PLU → new barcode mapping
            _save_plu_map(self.sales_row.get("plu"), sales_bc)
            QMessageBox.information(self, "Matched",
                f"✓ '{prod['description']}' barcode updated to {sales_bc}")
        else:
            # Persist the PLU → existing barcode mapping
            _save_plu_map(self.sales_row.get("plu"), existing_bc)
            QMessageBox.information(self, "Matched",
                f"✓ Linked to:\n\n  {prod['description']}\n"
                f"  Barcode: {existing_bc}\n  Dept: {prod.get('dept_name','')}")
        self.accept()

    def _update_barcode(self, old_bc: str, new_bc: str):
        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO products
                    (barcode,base_sku,description,department_id,supplier_id,
                     brand,unit,unit_size,units_per_carton,sell_price,cost_price,
                     carton_price,tax_rate,reorder_point,variable_weight,
                     expected,active,notes,created_at,updated_at)
                SELECT ?,base_sku,description,department_id,supplier_id,
                     brand,unit,unit_size,units_per_carton,sell_price,cost_price,
                     carton_price,tax_rate,reorder_point,variable_weight,
                     expected,active,notes,created_at,CURRENT_TIMESTAMP
                FROM products WHERE barcode=?
            """, (new_bc, old_bc))
            conn.execute("""
                INSERT OR IGNORE INTO stock_on_hand (barcode,quantity)
                SELECT ?,quantity FROM stock_on_hand WHERE barcode=?
            """, (new_bc, old_bc))
            conn.execute("DELETE FROM stock_on_hand WHERE barcode=?", (old_bc,))
            conn.execute("DELETE FROM products WHERE barcode=?", (old_bc,))
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    def _add_new(self):
        prefill = {
            "barcode":      self.sales_row.get("barcode",""),
            "description":  self.sales_row.get("plu_name",""),
            "dept_name":    self.sales_row.get("sub_group",""),
        }
        dlg = _AddProductDialog(prefill, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Persist the PLU → new barcode mapping
            _save_plu_map(self.sales_row.get("plu"), dlg.saved_barcode)
            QMessageBox.information(self, "Product Added",
                f"✓ New product saved:\n\n"
                f"  {dlg.f_desc.text()}\n  Barcode: {dlg.saved_barcode}")
            self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Main Sales Report View
# ─────────────────────────────────────────────────────────────────────────────
class SalesReportView(QWidget):
    def __init__(self):
        super().__init__()
        _ensure_plu_map_table()   # create plu_barcode_map if not exists
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Sales Report")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setMinimumHeight(34)
        filter_row.addWidget(self.date_from)

        filter_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setMinimumHeight(34)
        filter_row.addWidget(self.date_to)

        filter_row.addWidget(QLabel("Group:"))
        self.group_filter = QComboBox()
        self.group_filter.addItem("All Groups", None)
        self.group_filter.setMinimumHeight(34)
        filter_row.addWidget(self.group_filter)

        load_btn = QPushButton("Apply")
        load_btn.setMinimumHeight(34)
        load_btn.setStyleSheet("background:#1565c0;color:white;font-weight:bold;padding:0 16px;")
        load_btn.clicked.connect(self._load)
        filter_row.addWidget(load_btn)

        import_btn = QPushButton("⬆  Import Sales")
        import_btn.setMinimumHeight(34)
        import_btn.setStyleSheet("background:#2e7d32;color:white;font-weight:bold;padding:0 16px;")
        import_btn.clicked.connect(self._import_sales)
        filter_row.addWidget(import_btn)

        export_btn = QPushButton("⬇  Export CSV")
        export_btn.setMinimumHeight(34)
        export_btn.clicked.connect(self._export)
        filter_row.addWidget(export_btn)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Stat cards
        cards_row = QHBoxLayout()
        self._card_revenue, self._val_revenue, _ = _stat_card("Net Revenue",      "$0.00", "#4CAF50")
        self._card_qty,     self._val_qty,     _ = _stat_card("Total Items Sold", "0",     "#2196F3")
        self._card_days,    self._val_days,    _ = _stat_card("Days of Data",     "0",     "#FF9800")
        self._card_top,     self._val_top, self._lbl_top = _stat_card("Top Seller", "—",  "#9C27B0")
        for c in [self._card_revenue, self._card_qty, self._card_days, self._card_top]:
            cards_row.addWidget(c)
        layout.addLayout(cards_row)

        # Tabs
        tabs = QTabWidget()

        # Col: 0=Barcode 1=PLU 2=Description 3=Department
        #      4=On Hand 5=Total Qty 6=Total Sales$ 7=Avg/Day$ 8=%Sales
        self.product_table = _make_table(
            ["Barcode", "PLU", "Description", "Department",
             "On Hand", "Total Qty", "Total Sales $", "Avg/Day $", "% of Sales"],
            stretch_col=2   # Description stretches
        )
        # All columns interactively resizable; Description fills remaining space
        _hdr = self.product_table.horizontalHeader()
        for _c in range(9):
            _hdr.setSectionResizeMode(_c, QHeaderView.ResizeMode.Interactive)
        _hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.product_table.setColumnWidth(0, 110)  # Barcode
        self.product_table.setColumnWidth(1, 55)   # PLU
        # col 2 Description stretches
        self.product_table.setColumnWidth(3, 120)  # Department
        self.product_table.setColumnWidth(4, 70)   # On Hand
        self.product_table.setColumnWidth(5, 80)   # Total Qty
        self.product_table.setColumnWidth(6, 110)  # Total Sales $
        self.product_table.setColumnWidth(7, 95)   # Avg/Day $
        self.product_table.setColumnWidth(8, 85)   # % of Sales

        # Right-click context menu
        self.product_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.product_table.customContextMenuRequested.connect(self._show_context_menu)
        self.product_table.doubleClicked.connect(
            lambda idx: self._open_match(self._get_row_data(idx.row())))

        tabs.addTab(self.product_table, "By Product")

        # Tab 2: By Day
        self.day_table = _make_table(
            ["Date", "Items Sold", "Total Sales $", "Discount $", "Net Sales $"],
            stretch_col=0)
        self.day_table.setColumnWidth(0, 120)
        tabs.addTab(self.day_table, "By Day")

        # Tab 3: By Sub Group
        self.group_table = _make_table(
            ["Sub Group", "Total Qty", "Total Sales $", "% of Sales"],
            stretch_col=0)
        tabs.addTab(self.group_table, "By Sub Group")

        layout.addWidget(tabs)

        self.footer_label = QLabel("")
        self.footer_label.setStyleSheet("color:#aaa;font-size:11px;")
        layout.addWidget(self.footer_label)

    # ── Data loading ──────────────────────────────────────────────────────────
    def _get_dates(self):
        return (self.date_from.date().toString("yyyy-MM-dd"),
                self.date_to.date().toString("yyyy-MM-dd"))

    def _load_groups(self):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT sub_group FROM sales_daily "
                "WHERE sub_group IS NOT NULL ORDER BY sub_group"
            ).fetchall()
            current = self.group_filter.currentData()
            self.group_filter.blockSignals(True)
            self.group_filter.clear()
            self.group_filter.addItem("All Groups", None)
            for r in rows:
                self.group_filter.addItem(r[0], r[0])
            idx = self.group_filter.findData(current)
            if idx >= 0: self.group_filter.setCurrentIndex(idx)
            self.group_filter.blockSignals(False)
        except Exception:
            pass
        conn.close()

    def _load(self):
        conn = get_connection()
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sales_daily'"
        ).fetchone()
        if not exists:
            conn.close()
            self.footer_label.setText(
                "No sales data yet — import a CSV or PDF using the ⬆ Import Sales button.")
            return

        d_from, d_to = self._get_dates()
        group = self.group_filter.currentData()
        where  = "WHERE sale_date BETWEEN ? AND ?"
        params = [d_from, d_to]
        if group:
            where += " AND sub_group = ?"
            params.append(group)

        # Stats
        stats = conn.execute(f"""
            SELECT SUM(sales_dollars) + SUM(discount), SUM(quantity), COUNT(DISTINCT sale_date)
            FROM sales_daily {where}
        """, params).fetchone()
        total_rev  = stats[0] or 0
        total_qty  = stats[1] or 0
        total_days = stats[2] or 0

        top = conn.execute(f"""
            SELECT plu_name, SUM(sales_dollars) as s
            FROM sales_daily {where}
            GROUP BY plu ORDER BY s DESC LIMIT 1
        """, params).fetchone()

        self._val_revenue.setText(f"${total_rev:,.2f}")
        self._val_qty.setText(f"{int(total_qty):,}")
        self._val_days.setText(str(total_days))
        self._val_top.setText(f"${top[1]:,.2f}" if top else "—")
        self._lbl_top.setText(top[0][:30] if top else "Top Seller")

        # ── By Product ────────────────────────────────────────────────────────
        # Load ALL products from DB keyed by PLU (zero-padded barcode)
        # so we can join full product data onto each sales row.
        all_prods_rows = conn.execute("""
            SELECT p.barcode, p.plu, p.description, p.brand,
                   d.name  AS dept_name,
                   s.name  AS supplier_name,
                   p.unit, p.sell_price, p.cost_price,
                   COALESCE(soh.quantity, 0) AS on_hand
            FROM products p
            LEFT JOIN departments  d   ON p.department_id = d.id
            LEFT JOIN suppliers    s   ON p.supplier_id   = s.id
            LEFT JOIN stock_on_hand soh ON soh.barcode    = p.barcode
            WHERE p.active = 1
        """).fetchall()
        all_prods = [dict(r) for r in all_prods_rows]

        # Build lookup: plu_int → product dict
        # Barcode format in this store is zero-padded PLU, e.g. PLU 39 → barcode "0200039"
        plu_to_prod = {}
        bc_to_prod  = {}
        for p in all_prods:
            bc = p["barcode"] or ""
            bc_to_prod[bc] = p
            # Strip leading zeros to get PLU integer
            stripped = bc.lstrip("0")
            if stripped.isdigit():
                plu_to_prod[int(stripped)] = p
            # Also index by plu if numeric
            sku = p.get("plu") or ""
            if sku.isdigit():
                plu_to_prod[int(sku)] = p
            # Store-specific: barcode format is "02" + zero-padded PLU
            # e.g. PLU 598 → barcode "0200598" → strip "02" prefix → "00598" → 598
            if bc.startswith("02") and len(bc) == 7:
                inner = bc[2:].lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p
            # Also handle 7-digit barcodes starting with 0 (pure zero-padded PLU)
            if len(bc) == 7 and bc.startswith("0") and not bc.startswith("02"):
                inner = bc.lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p

        # Priority-0: persistent PLU→barcode map (set by operator via Match Item)
        saved_plu_map = _load_plu_map()   # {plu_int: barcode}

        # Sales aggregates per PLU
        products = conn.execute(f"""
            SELECT
                sd.plu,
                sd.plu_name,
                sd.sub_group,
                SUM(sd.quantity)      AS qty,
                SUM(sd.sales_dollars) AS sales,
                SUM(sd.sales_dollars) / NULLIF(COUNT(DISTINCT sd.sale_date),0) AS avg_day
            FROM sales_daily sd
            {where}
            GROUP BY sd.plu
            ORDER BY sales DESC
        """, params).fetchall()

        self.product_table.setSortingEnabled(False)
        self.product_table.setRowCount(0)

        for row in products:
            plu      = row[0] or ""
            plu_name = row[1] or ""
            sub_grp  = row[2] or ""
            qty      = row[3] or 0
            sales    = row[4] or 0
            avg_day  = row[5] or 0
            pct      = (sales / total_rev * 100) if total_rev else 0

            # ── Product lookup (priority order) ──────────────────────────
            # 0. Persistent PLU map (operator-confirmed matches)
            prod = None
            try:
                plu_int = int(str(plu).strip())
                saved_bc = saved_plu_map.get(plu_int)
                if saved_bc:
                    prod = bc_to_prod.get(saved_bc)
            except (ValueError, TypeError):
                plu_int = None
            # 1. PLU integer → zero-padded barcode lookup
            if prod is None and plu_int is not None:
                prod = plu_to_prod.get(plu_int)
            # 2. PLU itself is a barcode
            if prod is None:
                prod = bc_to_prod.get(str(plu).strip())
            # 3. Auto-assign: PLU exactly matches product plu field
            if prod is None and plu_int is not None:
                for p in all_prods:
                    try:
                        if int(str(p.get("plu") or "").strip()) == plu_int:
                            prod = p
                            _save_plu_map(plu_int, p["barcode"])
                            break
                    except (ValueError, TypeError):
                        pass
            # 3. No match → prod stays None; row still shown with empty product fields

            barcode      = prod["barcode"]       if prod else ""
            # If matched: use DB description only.
            # If unmatched: combine plu_name + sub_group (PDF parser splits the name across both)
            if prod:
                description = prod["description"]
            else:
                # sub_group often contains the rest of the product name truncated by PDF parser
                # e.g. plu_name="QUINCEY", sub_group="JONES REAL TOMATO SAUCE GROCERY ALL"
                # Strip trailing dept/category words that aren't part of the name
                raw = plu_name.strip()
                description = raw
            dept_name    = prod["dept_name"]     if prod else ""
            sell_price   = prod["sell_price"]    if prod else 0
            cost_price   = prod["cost_price"]    if prod else 0
            on_hand      = prod["on_hand"]       if prod else ""

            r = self.product_table.rowCount()
            self.product_table.insertRow(r)

            bc_item = _item(barcode, CENTER)
            if not barcode:
                bc_item.setForeground(QColor("#f85149"))   # red = unmatched

            desc_item = _item(description)
            desc_item.setData(Qt.ItemDataRole.UserRole, {
                "plu":         plu,
                "plu_name":    plu_name,
                "sub_group":   sub_grp,
                "barcode":     barcode,
                "total_qty":   qty,
                "total_sales": sales,
                "sell_price":  sell_price,
                "dept_name":   dept_name,
            })

            pct_item = _item(f"{pct:.1f}%", RIGHT, numeric=True)
            if pct > 5:
                pct_item.setForeground(QColor("#4CAF50"))

            on_hand_item = _item(
                f"{on_hand:.0f}" if on_hand != "" else "—", RIGHT, numeric=bool(on_hand)
            )
            if isinstance(on_hand, (int, float)) and on_hand < 0:
                on_hand_item.setForeground(QColor("#f85149"))

            self.product_table.setItem(r, 0, bc_item)
            self.product_table.setItem(r, 1, _item(str(plu), CENTER))
            self.product_table.setItem(r, 2, desc_item)
            self.product_table.setItem(r, 3, _item(dept_name))
            self.product_table.setItem(r, 4, on_hand_item)
            self.product_table.setItem(r, 5, _item(f"{qty:.0f}", RIGHT, numeric=True))
            self.product_table.setItem(r, 6, _item(f"${sales:.2f}", RIGHT, numeric=True))
            self.product_table.setItem(r, 7, _item(f"${avg_day:.2f}", RIGHT, numeric=True))
            self.product_table.setItem(r, 8, pct_item)

        self.product_table.setSortingEnabled(True)

        # By Day
        days = conn.execute(f"""
            SELECT sale_date, SUM(quantity), SUM(sales_dollars),
                   SUM(discount), SUM(sales_dollars)+SUM(discount)
            FROM sales_daily {where}
            GROUP BY sale_date ORDER BY sale_date DESC
        """, params).fetchall()

        self.day_table.setSortingEnabled(False)
        self.day_table.setRowCount(0)
        for row in days:
            r = self.day_table.rowCount(); self.day_table.insertRow(r)
            self.day_table.setItem(r, 0, _item(row[0] or ""))
            self.day_table.setItem(r, 1, _item(f"{row[1]:.0f}", RIGHT, numeric=True))
            self.day_table.setItem(r, 2, _item(f"${row[2]:.2f}", RIGHT, numeric=True))
            self.day_table.setItem(r, 3, _item(f"${abs(row[3]):.2f}", RIGHT, numeric=True))
            self.day_table.setItem(r, 4, _item(f"${row[4]:.2f}", RIGHT, numeric=True))
        self.day_table.setSortingEnabled(True)

        # By Group
        groups = conn.execute(f"""
            SELECT sub_group, SUM(quantity), SUM(sales_dollars)
            FROM sales_daily {where}
            GROUP BY sub_group ORDER BY SUM(sales_dollars) DESC
        """, params).fetchall()

        self.group_table.setSortingEnabled(False)
        self.group_table.setRowCount(0)
        for row in groups:
            r = self.group_table.rowCount(); self.group_table.insertRow(r)
            pct = (row[2] / total_rev * 100) if total_rev else 0
            self.group_table.setItem(r, 0, _item(row[0] or ""))
            self.group_table.setItem(r, 1, _item(f"{row[1]:.0f}", RIGHT, numeric=True))
            self.group_table.setItem(r, 2, _item(f"${row[2]:.2f}", RIGHT, numeric=True))
            self.group_table.setItem(r, 3, _item(f"{pct:.1f}%", RIGHT, numeric=True))
        self.group_table.setSortingEnabled(True)

        conn.close()
        self._load_groups()
        self.footer_label.setText(
            f"Showing data from {d_from} to {d_to}  |  "
            f"{len(products)} products  |  {total_days} days  "
            f"  ·  Right-click any row to match or add a product"
        )

    # ── Right-click ───────────────────────────────────────────────────────────
    def _get_row_data(self, row_idx: int) -> dict:
        item = self.product_table.item(row_idx, 2)   # Name column holds UserRole data
        return item.data(Qt.ItemDataRole.UserRole) if item else {}

    def _show_context_menu(self, pos):
        row_idx = self.product_table.rowAt(pos.y())
        if row_idx < 0: return
        row_data = self._get_row_data(row_idx)
        if not row_data: return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:#1e2a38;border:1px solid #2a3a4a;
                  color:#e6edf3;font-size:12px;padding:4px;}
            QMenu::item{padding:7px 20px;border-radius:4px;}
            QMenu::item:selected{background:#1565c0;}
            QMenu::separator{height:1px;background:#2a3a4a;margin:4px 8px;}
        """)

        act_match = QAction("🔗  Match Item…", self)
        act_match.triggered.connect(lambda: self._open_match(row_data))
        menu.addAction(act_match)

        menu.addSeparator()

        act_view = QAction("👁  View Product", self)
        act_view.triggered.connect(lambda: self._view_product(row_data))
        if not row_data.get("barcode"):
            act_view.setEnabled(False)
        menu.addAction(act_view)

        menu.exec(self.product_table.viewport().mapToGlobal(pos))

    def _open_match(self, row_data: dict):
        if not row_data: return

        # Auto-assign if exactly one score-100 candidate exists
        all_prods = _get_all_products()
        query = row_data.get("plu_name", "")
        sales_plu = row_data.get("plu", "")
        perfect = []
        for p in all_prods:
            s = _fuzzy_score(query, p.get("description", ""))
            if p.get("barcode","").lower().startswith(str(sales_plu).lower()) and str(sales_plu).isdigit():
                s = 98
            if _plu_score(sales_plu, p.get("plu","")) == 100:
                s = 100
            if s == 100:
                perfect.append(p)
        if len(perfect) == 1:
            _save_plu_map(row_data.get("plu"), perfect[0]["barcode"])
            self._load()
            return

        # Otherwise open dialog for manual selection
        dlg = _MatchItemDialog(row_data, parent=self)
        if dlg.exec():
            self._load()

    def _view_product(self, row_data: dict):
        import models.product as prod_model
        bc = row_data.get("barcode","").strip()
        if not bc: return
        prod = prod_model.get_by_barcode(bc)
        if prod:
            QMessageBox.information(self, "Product",
                f"Barcode:     {prod['barcode']}\n"
                f"Description: {prod['description']}\n"
                f"Department:  {prod.get('dept_name','')}\n"
                f"Sell Price:  ${prod.get('sell_price',0):.2f}\n"
                f"Cost Price:  ${prod.get('cost_price',0):.2f}")
        else:
            QMessageBox.warning(self, "Not Found", f"No product for barcode {bc!r}")

    # ── Import / Export ───────────────────────────────────────────────────────
    def _import_sales(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Daily PLU Sales File(s)",
            os.path.expanduser("~/Downloads"),
            "Sales Files (*.csv *.pdf);;CSV Files (*.csv);;PDF Files (*.pdf)")
        if not paths: return

        # Import the script as a module directly — works in both dev and
        # PyInstaller exe environments without needing subprocess/sys.executable
        import sys as _sys
        import importlib.util

        if getattr(_sys, "frozen", False):
            script = os.path.join(_sys._MEIPASS, "scripts", "import_sales.py")
        else:
            script = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "..", "scripts", "import_sales.py"))

        if not os.path.exists(script):
            QMessageBox.critical(self, "Error",
                f"import_sales.py not found at:\n{script}")
            return

        try:
            spec   = importlib.util.spec_from_file_location("import_sales", script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.ensure_tables()

            errors = []
            for path in paths:
                try:
                    module.import_file(path)
                except Exception as e:
                    errors.append(f"{os.path.basename(path)}: {e}")

            if errors:
                QMessageBox.warning(self, "Import Warnings",
                    "Some files had errors:\n" + "\n".join(errors))
            else:
                QMessageBox.information(self, "Import Complete",
                    f"Imported {len(paths)} file(s).\nDashboard will now refresh.")
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))
            return

        self._load()

    def _export(self):
        d_from, d_to = self._get_dates()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Sales CSV",
            f"sales_{d_from}_to_{d_to}.csv", "CSV (*.csv)")
        if not path: return

        group  = self.group_filter.currentData()
        where  = "WHERE sd.sale_date BETWEEN ? AND ?"
        params = [d_from, d_to]
        if group:
            where += " AND sd.sub_group = ?"
            params.append(group)

        conn = get_connection()

        # ── Total revenue for % of sales calculation ──────────────────
        total_rev = conn.execute(
            f"SELECT COALESCE(SUM(sales_dollars),0) FROM sales_daily sd {where}",
            params
        ).fetchone()[0] or 0

        total_days = conn.execute(
            f"SELECT COUNT(DISTINCT sale_date) FROM sales_daily sd {where}",
            params
        ).fetchone()[0] or 1

        # ── Same aggregation query as the screen ──────────────────────
        agg_rows = conn.execute(f"""
            SELECT
                sd.plu,
                sd.plu_name,
                sd.sub_group,
                SUM(sd.quantity)      AS qty,
                SUM(sd.sales_dollars) AS sales,
                SUM(sd.sales_dollars) / NULLIF(COUNT(DISTINCT sd.sale_date), 0) AS avg_day
            FROM sales_daily sd
            {where}
            GROUP BY sd.plu
            ORDER BY sales DESC
        """, params).fetchall()

        # ── Build product lookups (same as _load) ─────────────────────
        all_prods_rows = conn.execute("""
            SELECT p.barcode, p.plu, p.description,
                   d.name AS dept_name,
                   COALESCE(soh.quantity, 0) AS on_hand
            FROM products p
            LEFT JOIN departments   d   ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh ON soh.barcode     = p.barcode
            WHERE p.active = 1
        """).fetchall()
        conn.close()

        all_prods   = [dict(r) for r in all_prods_rows]
        bc_to_prod  = {p["barcode"]: p for p in all_prods}
        plu_to_prod = {}
        for p in all_prods:
            bc = p["barcode"] or ""
            stripped = bc.lstrip("0")
            if stripped.isdigit():
                plu_to_prod[int(stripped)] = p
            sku = p.get("plu") or ""
            if sku.isdigit():
                plu_to_prod[int(sku)] = p
            if bc.startswith("02") and len(bc) == 7:
                inner = bc[2:].lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p
            if len(bc) == 7 and bc.startswith("0") and not bc.startswith("02"):
                inner = bc.lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p

        saved_plu_map = _load_plu_map()

        # ── Write CSV ─────────────────────────────────────────────────
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "Barcode", "PLU", "Description", "Sub Group", "Department",
                "On Hand", "Total Qty", "Total Sales $", "Avg/Day $",
                "% of Sales", "Matched"
            ])

            for row in agg_rows:
                plu      = row[0] or ""
                plu_name = row[1] or ""
                sub_grp  = row[2] or ""
                qty      = row[3] or 0
                sales    = row[4] or 0
                avg_day  = row[5] or 0
                pct      = (sales / total_rev * 100) if total_rev else 0

                # Resolve product — same priority order as screen
                prod = None
                try:
                    plu_int  = int(str(plu).strip())
                    saved_bc = saved_plu_map.get(plu_int)
                    if saved_bc:
                        prod = bc_to_prod.get(saved_bc)
                except (ValueError, TypeError):
                    plu_int = None
                if prod is None and plu_int is not None:
                    prod = plu_to_prod.get(plu_int)
                if prod is None:
                    prod = bc_to_prod.get(str(plu).strip())

                barcode   = prod["barcode"]   if prod else ""
                dept      = prod["dept_name"] if prod else ""
                on_hand   = prod["on_hand"]   if prod else ""
                desc      = prod["description"] if prod else plu_name
                matched   = "Yes" if prod else "No"

                w.writerow([
                    barcode,
                    plu,
                    desc,
                    sub_grp,
                    dept,
                    f"{on_hand:.0f}" if on_hand != "" else "",
                    f"{qty:.0f}",
                    f"{sales:.2f}",
                    f"{avg_day:.2f}",
                    f"{pct:.1f}%",
                    matched,
                ])

        matched_count   = sum(1 for r in agg_rows
                              if saved_plu_map.get(
                                  int(str(r[0]).strip()) if str(r[0]).strip().isdigit() else -1
                              ) or plu_to_prod.get(
                                  int(str(r[0]).strip()) if str(r[0]).strip().isdigit() else -1
                              ))
        unmatched_count = len(agg_rows) - matched_count
        QMessageBox.information(
            self, "Exported",
            f"Saved to {path}\n\n"
            f"{len(agg_rows)} products exported\n"
            f"Matched: {matched_count}  |  Unmatched: {unmatched_count}"
        )
