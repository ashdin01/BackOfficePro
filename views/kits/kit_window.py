from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDoubleSpinBox,
    QSpinBox, QRadioButton, QMessageBox, QDialog, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
import controllers.kit_controller as kit_ctrl
import controllers.product_controller as product_ctrl
import config.styles as styles
from utils.stock_events import stock_events


def _fmt_qty(q):
    return f"{q:g}"


class _ProductPicker(QDialog):
    """Search for a product by barcode / PLU / description and return the pick."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 380)
        self.barcode = None
        self.description = None

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by barcode, PLU or description…")
        self.search.setMinimumHeight(34)
        layout.addWidget(self.search)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Barcode", "PLU", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 80)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._accept_row)
        layout.addWidget(self.table)

        hint = QLabel("Enter or double-click to choose")
        hint.setStyleSheet(styles.STYLE_LABEL_MUTED)
        layout.addWidget(hint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._search)
        self.search.textChanged.connect(lambda _: self._timer.start())
        self.search.returnPressed.connect(self._enter)
        QShortcut(QKeySequence("Escape"), self, self.reject)
        self.search.setFocus()

    def _search(self):
        rows = product_ctrl.search_products(self.search.text(), active_only=True, limit=50)
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(row['plu'] or ''))
            self.table.setItem(r, 2, QTableWidgetItem(row['description'] or ''))
        if rows:
            self.table.selectRow(0)

    def _enter(self):
        if self._timer.isActive():
            self._timer.stop()
            self._search()
        self._accept_row()

    def _accept_row(self):
        r = self.table.currentRow()
        if r < 0:
            return
        self.barcode = self.table.item(r, 0).text()
        self.description = self.table.item(r, 2).text()
        self.accept()


class KitWindow(QWidget):
    """Define kit recipes (e.g. Xmas hampers) and build / break down batches."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kits / Hampers")
        self.resize(860, 760)
        self._parent_barcode = None
        self._build_ui()
        self._load_kits()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Kits / Hampers")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {styles.CLR_TEXT};")
        layout.addWidget(title)
        note = QLabel(
            "A kit is a normal product (its own barcode/PLU and stock) made from component "
            "products. Build a batch to move stock from the components into the kit; sales then "
            "reduce the kit's own stock."
        )
        note.setWordWrap(True)
        note.setStyleSheet(styles.STYLE_LABEL_MUTED)
        layout.addWidget(note)

        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel("Kit:"))
        self.kit_combo = QComboBox()
        self.kit_combo.setMinimumWidth(380)
        self.kit_combo.currentIndexChanged.connect(self._on_kit_selected)
        pick_row.addWidget(self.kit_combo, 1)
        btn_new = QPushButton("+ New Kit…")
        btn_new.setFixedHeight(30)
        btn_new.clicked.connect(self._new_kit)
        pick_row.addWidget(btn_new)
        layout.addLayout(pick_row)

        layout.addWidget(QLabel("<b>Components (per 1 kit)</b>"))
        self.comp_table = QTableWidget(0, 6)
        self.comp_table.setHorizontalHeaderLabels(
            ["Barcode", "Description", "Qty", "Unit Cost", "On Hand", ""])
        h = self.comp_table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.comp_table.setColumnWidth(0, 130)
        self.comp_table.setColumnWidth(2, 80)
        self.comp_table.setColumnWidth(3, 90)
        self.comp_table.setColumnWidth(4, 80)
        self.comp_table.setColumnWidth(5, 40)
        self.comp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.comp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.comp_table.verticalHeader().setVisible(False)
        layout.addWidget(self.comp_table, 1)

        comp_row = QHBoxLayout()
        self.btn_add_comp = QPushButton("+ &Add Component…")
        self.btn_add_comp.setFixedHeight(30)
        self.btn_add_comp.setToolTip("Add a component  [Alt+A]")
        self.btn_add_comp.clicked.connect(self._add_component)
        comp_row.addWidget(self.btn_add_comp)
        comp_row.addStretch()
        self.summary = QLabel("")
        self.summary.setStyleSheet(f"font-weight: bold; color: {styles.CLR_TEXT};")
        comp_row.addWidget(self.summary)
        layout.addLayout(comp_row)

        # ── Build panel ──────────────────────────────────────────────────────
        layout.addWidget(QLabel("<b>Build a batch</b>"))
        build_row = QHBoxLayout()
        self.rb_build = QRadioButton("Build")
        self.rb_build.setChecked(True)
        self.rb_break = QRadioButton("Break down")
        self.rb_break.setToolTip("Return unsold kits to their component stock")
        build_row.addWidget(self.rb_build)
        build_row.addWidget(self.rb_break)
        build_row.addWidget(QLabel("Quantity:"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 9999)
        self.qty_spin.setFixedWidth(90)
        build_row.addWidget(self.qty_spin)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Notes (optional)")
        build_row.addWidget(self.notes, 1)
        self.btn_build = QPushButton("Build  [Ctrl+Enter]")
        self.btn_build.setFixedHeight(34)
        self.btn_build.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
            "border-radius: 4px; padding: 0 20px; font-weight: bold; }"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}")
        self.btn_build.clicked.connect(self._do_build)
        build_row.addWidget(self.btn_build)
        layout.addLayout(build_row)
        self.rb_build.toggled.connect(self._update_build_label)
        QShortcut(QKeySequence("Ctrl+Return"), self, self._do_build)

        layout.addWidget(QLabel("<b>Recent builds</b>"))
        self.hist = QTableWidget(0, 6)
        self.hist.setHorizontalHeaderLabels(
            ["Ref", "Date", "Kit", "Qty", "Unit Cost", "By / Notes"])
        self.hist.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.hist.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.hist.setColumnWidth(0, 80)
        self.hist.setColumnWidth(1, 130)
        self.hist.setColumnWidth(3, 60)
        self.hist.setColumnWidth(4, 80)
        self.hist.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist.verticalHeader().setVisible(False)
        self.hist.setMaximumHeight(150)
        layout.addWidget(self.hist)

        QShortcut(QKeySequence("Escape"), self, self.close)

    # ── Loading ───────────────────────────────────────────────────────────────
    def _load_kits(self, select_barcode=None):
        select_barcode = select_barcode or self._parent_barcode
        kits = kit_ctrl.get_kits()
        self.kit_combo.blockSignals(True)
        self.kit_combo.clear()
        for k in kits:
            self.kit_combo.addItem(
                f"{k['description']}  ({k['plu'] or k['barcode']})", k['barcode'])
        idx = self.kit_combo.findData(select_barcode) if select_barcode else -1
        if idx < 0 and kits:
            idx = 0
        self.kit_combo.setCurrentIndex(idx)
        self.kit_combo.blockSignals(False)
        self._parent_barcode = self.kit_combo.currentData() if idx >= 0 else None
        self._load_kit()

    def _on_kit_selected(self):
        self._parent_barcode = self.kit_combo.currentData()
        self._load_kit()

    def _load_kit(self):
        has_kit = bool(self._parent_barcode)
        for w in (self.btn_add_comp, self.btn_build, self.qty_spin, self.notes,
                  self.rb_build, self.rb_break):
            w.setEnabled(has_kit)
        self.comp_table.setRowCount(0)
        if not has_kit:
            self.summary.setText("No kit selected — choose “+ New Kit…” to start one.")
            self._load_history()
            return
        comps = kit_ctrl.get_components(self._parent_barcode)
        for c in comps:
            r = self.comp_table.rowCount()
            self.comp_table.insertRow(r)
            self.comp_table.setItem(r, 0, QTableWidgetItem(c['barcode']))
            self.comp_table.setItem(r, 1, QTableWidgetItem(c['description'] or ''))
            sb = QDoubleSpinBox()
            sb.setRange(0.01, 9999)
            sb.setDecimals(2)
            sb.setValue(c['qty'])
            sb.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            sb.setToolTip("How many of this component go into one kit")
            sb.editingFinished.connect(lambda cid=c['id'], s=sb: self._qty_changed(cid, s))
            self.comp_table.setCellWidget(r, 2, sb)
            cost = QTableWidgetItem(f"${(c['cost_price'] or 0):.4f}")
            cost.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.comp_table.setItem(r, 3, cost)
            soh = QTableWidgetItem(_fmt_qty(c['soh']))
            soh.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c['soh'] < c['qty']:
                soh.setForeground(Qt.GlobalColor.red)
            self.comp_table.setItem(r, 4, soh)
            btn = QPushButton("✕")
            btn.setStyleSheet(
                f"color: {styles.CLR_DANGER_ALT}; font-weight: bold; border: none; background: transparent;")
            btn.clicked.connect(lambda _, cid=c['id']: self._remove_component(cid))
            self.comp_table.setCellWidget(r, 5, btn)
        cost = kit_ctrl.get_recipe_cost(self._parent_barcode)
        self.summary.setText(
            f"Recipe cost ${cost:.2f} per kit   |   Fully stocked for: "
            f"{kit_ctrl.get_max_buildable(self._parent_barcode)}")
        self._update_build_label()
        self._load_history()

    def _load_history(self):
        rows = kit_ctrl.get_builds(self._parent_barcode, limit=50) if self._parent_barcode else []
        self.hist.setRowCount(0)
        for b in rows:
            r = self.hist.rowCount()
            self.hist.insertRow(r)
            who = b['created_by'] or ''
            self.hist.setItem(r, 0, QTableWidgetItem(f"ASM-{b['id']}"))
            self.hist.setItem(r, 1, QTableWidgetItem(str(b['created_at'])[:16]))
            self.hist.setItem(r, 2, QTableWidgetItem(b['description'] or ''))
            q = QTableWidgetItem(f"{b['qty']:+g}")
            q.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            q.setForeground(Qt.GlobalColor.darkGreen if b['qty'] > 0 else Qt.GlobalColor.red)
            self.hist.setItem(r, 3, q)
            self.hist.setItem(r, 4, QTableWidgetItem(f"${(b['unit_cost'] or 0):.2f}"))
            self.hist.setItem(r, 5, QTableWidgetItem(
                f"{who}  {b['notes']}".strip() if b['notes'] else who))

    def _update_build_label(self):
        self.btn_build.setText(
            "Build  [Ctrl+Enter]" if self.rb_build.isChecked() else "Break Down  [Ctrl+Enter]")

    # ── Recipe editing ────────────────────────────────────────────────────────
    def _new_kit(self):
        dlg = _ProductPicker("Choose the kit product (e.g. the hamper)", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # A kit exists once it has a component; start by adding the first one.
        self._parent_barcode = dlg.barcode
        self.kit_combo.blockSignals(True)
        if self.kit_combo.findData(dlg.barcode) < 0:
            self.kit_combo.addItem(dlg.description, dlg.barcode)
        self.kit_combo.setCurrentIndex(self.kit_combo.findData(dlg.barcode))
        self.kit_combo.blockSignals(False)
        self._load_kit()
        self._add_component()

    def _add_component(self):
        if not self._parent_barcode:
            return
        dlg = _ProductPicker("Add a component", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            kit_ctrl.add_component(self._parent_barcode, dlg.barcode, 1)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot add component", str(e))
            return
        self._load_kits(self._parent_barcode)

    def _qty_changed(self, component_id, spin):
        try:
            kit_ctrl.update_component_qty(component_id, spin.value())
        except ValueError as e:
            QMessageBox.warning(self, "Invalid quantity", str(e))
        self._load_kit()

    def _remove_component(self, component_id):
        kit_ctrl.delete_component(component_id)
        self._load_kits(self._parent_barcode)

    # ── Build ─────────────────────────────────────────────────────────────────
    def _do_build(self):
        if not self._parent_barcode or not self.btn_build.isEnabled():
            return
        n = self.qty_spin.value()
        building = self.rb_build.isChecked()
        name = self.kit_combo.currentText().split("  (")[0]
        verb = "Build" if building else "Break down"
        effect = ("uses up the components and adds the kits to stock" if building
                  else "removes the kits from stock and returns the components")
        msg = f"{verb} {n} × {name}?\n\nThis {effect}."
        if building:
            short = kit_ctrl.get_shortages(self._parent_barcode, n)
            if short:
                msg += ("\n\nStock on hand is short for these components "
                        "(they will go to or below zero):\n" + "\n".join(
                            f"  • {x['description']}: need {x['need']:g}, have {x['have']:g}"
                            for x in short))
        if QMessageBox.question(
            self, f"{verb} kits", msg,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            build_id = kit_ctrl.build(
                self._parent_barcode, n if building else -n, self.notes.text().strip())
        except ValueError as e:
            QMessageBox.warning(self, f"Cannot {verb.lower()}", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Build failed — no stock was changed.\n\n{e}")
            return
        stock_events.changed.emit()
        self.notes.clear()
        self._load_kits(self._parent_barcode)
        self.summary.setText(self.summary.text() + f"   |   Last: ASM-{build_id}")
