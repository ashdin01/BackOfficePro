from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QDateEdit,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox,
    QTextEdit, QLabel, QLineEdit, QDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame
)
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from utils.error_dialog import show_error
from utils.text_search import matches_all_words
from views.widgets.search_bar import SearchBar
import config.styles as styles
import controllers.purchase_order_controller as po_ctrl
import controllers.supplier_controller as supplier_ctrl
from config.constants import PO_TYPES, PO_TYPE_PO


class _TypeLookup(QDialog):
    """F2 popup for selecting order type."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Order Type")
        self.setModal(True)
        self.setFixedWidth(360)
        self.setStyleSheet(
            f"QDialog{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};}}"
            f"QTableWidget{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};"
            f"gridline-color:{styles.CLR_BORDER};border:1px solid {styles.CLR_BORDER};}}"
            f"QTableWidget::item:selected{{background:{styles.CLR_ACCENT};}}"
            f"QHeaderView::section{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_MUTED};"
            "border:none;padding:4px 8px;font-weight:bold;}"
        )
        self.selected_code = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lbl = QLabel("Double-click or press Enter to select:")
        lbl.setStyleSheet(styles.STYLE_LABEL_MUTED)
        lay.addWidget(lbl)

        self.table = QTableWidget(len(PO_TYPES), 2)
        self.table.setHorizontalHeaderLabels(["Code", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 60)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        for r, (code, desc) in enumerate(PO_TYPES.items()):
            code_item = QTableWidgetItem(code)
            code_item.setFont(self.table.font())
            code_item.setData(Qt.ItemDataRole.UserRole, code)
            desc_item = QTableWidgetItem(desc)
            self.table.setItem(r, 0, code_item)
            self.table.setItem(r, 1, desc_item)

        self.table.selectRow(0)
        self.table.doubleClicked.connect(self._pick)
        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Select  [Enter]")
        btn_ok.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:6px 16px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}")
        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{styles.CLR_MUTED};"
            f"border:1px solid {styles.CLR_BORDER};border-radius:4px;padding:6px 14px;}}"
            f"QPushButton:hover{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};}}")
        btn_ok.clicked.connect(self._pick)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        QShortcut(QKeySequence("Return"), self, self._pick)
        QShortcut(QKeySequence("Enter"),  self, self._pick)
        QShortcut(QKeySequence("Escape"), self, self.reject)

    def _pick(self):
        row = self.table.currentRow()
        if row >= 0:
            self.selected_code = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.accept()


class _SupplierLookup(QDialog):
    """F3 popup for actively picking a supplier.

    No dropdown, no default selection — the order can't be created against
    a supplier the user never actually chose. Search-as-you-type narrows
    the list; double-click or Enter confirms.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Supplier")
        self.setModal(True)
        self.setFixedSize(420, 460)
        self.setStyleSheet(
            f"QDialog{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};}}"
            f"QTableWidget{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};"
            f"gridline-color:{styles.CLR_BORDER};border:1px solid {styles.CLR_BORDER};}}"
            f"QTableWidget::item:selected{{background:{styles.CLR_ACCENT};}}"
            f"QHeaderView::section{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_MUTED};"
            "border:none;padding:4px 8px;font-weight:bold;}"
        )
        self.selected_id = None
        self.selected_name = None
        self._all_suppliers = supplier_ctrl.get_all()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lbl = QLabel("Type to search, then double-click or press Enter:")
        lbl.setStyleSheet(styles.STYLE_LABEL_MUTED)
        lay.addWidget(lbl)

        self.search = SearchBar("Search suppliers by name or code…", interval=150)
        self.search.search_changed.connect(self._filter)
        lay.addWidget(self.search)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Code", "Name"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._pick)
        self._render(self._all_suppliers)
        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Select  [Enter]")
        btn_ok.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:6px 16px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}")
        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{styles.CLR_MUTED};"
            f"border:1px solid {styles.CLR_BORDER};border-radius:4px;padding:6px 14px;}}"
            f"QPushButton:hover{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};}}")
        btn_ok.clicked.connect(self._pick)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        QShortcut(QKeySequence("Return"), self, self._pick)
        QShortcut(QKeySequence("Enter"),  self, self._pick)
        QShortcut(QKeySequence("Escape"), self, self.reject)

        self.search.setFocus()

    def _filter(self):
        term = self.search.text()
        rows = [s for s in self._all_suppliers
                if matches_all_words(term, s['name'], s['code'])]
        self._render(rows)

    def _render(self, rows):
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            code_item = QTableWidgetItem(s['code'])
            code_item.setData(Qt.ItemDataRole.UserRole, s['id'])
            self.table.setItem(r, 0, code_item)
            self.table.setItem(r, 1, QTableWidgetItem(s['name']))
        if rows:
            self.table.selectRow(0)

    def _pick(self):
        row = self.table.currentRow()
        if row >= 0:
            self.selected_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.selected_name = self.table.item(row, 1).text()
            self.accept()


class POCreate(QWidget):
    def __init__(self, on_save=None, supplier_id=None):
        super().__init__()
        self.setWindowTitle("New Purchase Order")
        self.setMinimumWidth(440)
        self.on_save = on_save
        self._preset_supplier_id = supplier_id
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)

        # ── Order Type field ──────────────────────────────────────────
        type_row = QHBoxLayout()
        type_row.setSpacing(6)

        self.type_input = QLineEdit()
        self.type_input.setMaxLength(2)
        self.type_input.setFixedWidth(52)
        self.type_input.setFixedHeight(32)
        self.type_input.setText(PO_TYPE_PO)
        self.type_input.setPlaceholderText("PO")
        self.type_input.setStyleSheet(
            f"QLineEdit{{font-weight:bold;font-size:14px;text-transform:uppercase;"
            f"background:{styles.CLR_BG_PANEL};color:{styles.CLR_SUCCESS_ALT};border:1px solid {styles.CLR_BORDER};"
            "border-radius:4px;padding:2px 6px;}"
            f"QLineEdit:focus{{border-color:{styles.CLR_SUCCESS_ALT};}}")

        f2_btn = QPushButton("F2")
        f2_btn.setFixedHeight(32)
        f2_btn.setFixedWidth(34)
        f2_btn.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_MUTED};"
            f"border:1px solid {styles.CLR_BORDER};border-radius:4px;font-size:10px;}}"
            f"QPushButton:hover{{color:{styles.CLR_TEXT};border-color:{styles.CLR_MUTED};}}")
        f2_btn.clicked.connect(self._type_lookup)

        self.type_desc_lbl = QLabel(PO_TYPES[PO_TYPE_PO])
        self.type_desc_lbl.setStyleSheet(styles.STYLE_LABEL_MUTED)

        type_row.addWidget(self.type_input)
        type_row.addWidget(f2_btn)
        type_row.addWidget(self.type_desc_lbl)
        type_row.addStretch()

        type_container = QWidget()
        type_container.setLayout(type_row)
        form.addRow("Order Type", type_container)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(styles.STYLE_SEPARATOR)

        # ── Supplier field — must be actively picked, never defaults ────
        self._supplier_id = None
        self._supplier_name = None
        if self._preset_supplier_id:
            preset = supplier_ctrl.get_by_id(self._preset_supplier_id)
            if preset:
                self._supplier_id = preset['id']
                self._supplier_name = preset['name']

        supplier_row = QHBoxLayout()
        supplier_row.setSpacing(6)

        self.supplier_lbl = QLabel()
        self.supplier_lbl.setFixedHeight(32)
        supplier_row.addWidget(self.supplier_lbl, 1)

        supplier_btn = QPushButton("Select…  [F3]")
        supplier_btn.setFixedHeight(32)
        supplier_btn.setDefault(False)
        supplier_btn.setAutoDefault(False)
        supplier_btn.clicked.connect(self._select_supplier)
        supplier_row.addWidget(supplier_btn)

        supplier_container = QWidget()
        supplier_container.setLayout(supplier_row)

        self.delivery_date = QDateEdit()
        self.delivery_date.setCalendarPopup(True)
        self.delivery_date.setDate(QDate.currentDate().addDays(7))
        self.delivery_date.setDisplayFormat("dd/MM/yyyy")

        self.notes = QTextEdit()
        self.notes.setMaximumHeight(70)
        self.notes.setPlaceholderText("Optional notes...")

        form.addRow(sep)
        form.addRow("Supplier *", supplier_container)
        form.addRow("Expected Date", self.delivery_date)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        layout.addSpacing(8)

        # ── Action buttons ────────────────────────────────────────────
        hint = QLabel("Choose how to start this order:")
        hint.setStyleSheet(styles.STYLE_LABEL_MUTED)
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.setSpacing(8)

        self.rec_btn = QPushButton("📋  Recommended PO  [Ctrl+R]")
        self.rec_btn.setFixedHeight(38)
        self.rec_btn.setDefault(False)
        self.rec_btn.setAutoDefault(False)
        self.rec_btn.setToolTip("Pre-fill with products below reorder point (Purchase Orders only)")
        self.rec_btn.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;font-weight:bold;padding:0 12px;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
            f"QPushButton:disabled{{background:{styles.CLR_BG_PANEL};color:#555;}}")
        self.rec_btn.clicked.connect(lambda: self._save(blank=False))

        self.blank_btn = QPushButton("➕  Blank Order  [Ctrl+B]")
        self.blank_btn.setFixedHeight(38)
        self.blank_btn.setDefault(False)
        self.blank_btn.setAutoDefault(False)
        self.blank_btn.setToolTip("Create an empty order — add lines manually")
        self.blank_btn.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_SUCCESS_DARK};color:white;border:none;"
            "border-radius:4px;font-weight:bold;padding:0 12px;}"
            f"QPushButton:hover{{background:{styles.CLR_SUCCESS_HOVER};}}"
            f"QPushButton:disabled{{background:{styles.CLR_BG_PANEL};color:#555;}}")
        self.blank_btn.clicked.connect(lambda: self._save(blank=True))

        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(38)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.close)

        QShortcut(QKeySequence("F2"),     self, self._type_lookup)
        QShortcut(QKeySequence("F3"),     self, self._select_supplier)
        QShortcut(QKeySequence("Ctrl+R"), self, lambda: self._save(blank=False))
        QShortcut(QKeySequence("Ctrl+B"), self, lambda: self._save(blank=True))
        QShortcut(QKeySequence("Escape"), self, self.close)

        btns.addWidget(self.rec_btn)
        btns.addWidget(self.blank_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self.type_input.textChanged.connect(self._on_type_changed)
        self._on_type_changed(PO_TYPE_PO)
        self._refresh_supplier_label()

    def _type_lookup(self):
        dlg = _TypeLookup(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_code:
            self.type_input.setText(dlg.selected_code)

    def _select_supplier(self):
        dlg = _SupplierLookup(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_id:
            self._supplier_id = dlg.selected_id
            self._supplier_name = dlg.selected_name
            self._refresh_supplier_label()

    def _refresh_supplier_label(self):
        if self._supplier_id:
            self.supplier_lbl.setText(f"✓  {self._supplier_name}")
            self.supplier_lbl.setStyleSheet(
                f"color:{styles.CLR_TEXT};font-weight:bold;padding:4px 2px;")
        else:
            self.supplier_lbl.setText("⚠  No supplier selected")
            self.supplier_lbl.setStyleSheet(
                f"color:{styles.CLR_DANGER};font-weight:bold;padding:4px 2px;")
        self._update_action_buttons()

    def _update_action_buttons(self):
        code = self.type_input.text().upper().strip()
        has_supplier = self._supplier_id is not None
        # Recommended PO only makes sense for normal purchase orders
        self.rec_btn.setEnabled(has_supplier and code == PO_TYPE_PO)
        self.blank_btn.setEnabled(has_supplier)

    def _on_type_changed(self, text):
        code = text.upper().strip()
        desc = PO_TYPES.get(code, '')
        self.type_desc_lbl.setText(desc if desc else "— unknown type")
        _c = styles.CLR_MUTED if desc else styles.CLR_DANGER
        _ci = styles.CLR_SUCCESS_ALT if desc else styles.CLR_DANGER
        _b = styles.CLR_BORDER if desc else styles.CLR_DANGER
        self.type_desc_lbl.setStyleSheet(f"color:{_c}; font-size:11px;")
        self.type_input.setStyleSheet(
            f"QLineEdit{{font-weight:bold;font-size:14px;"
            f"background:{styles.CLR_BG_PANEL};color:{_ci};"
            f"border:1px solid {_b};"
            f"border-radius:4px;padding:2px 6px;}}"
            f"QLineEdit:focus{{border-color:{_ci};}}")
        self._update_action_buttons()

    def _save(self, blank=False):
        po_type = self.type_input.text().upper().strip()
        if po_type not in PO_TYPES:
            QMessageBox.warning(
                self, "Invalid Order Type",
                f"'{po_type}' is not a valid order type.\n\n"
                "Press F2 to choose: PO · RO · IO"
            )
            self.type_input.setFocus()
            return

        if not self._supplier_id:
            QMessageBox.warning(
                self, "Validation",
                "Please select a supplier before creating the order.\n\nPress F3 to choose one."
            )
            self._select_supplier()
            return

        try:
            po_id = po_ctrl.create_po(
                supplier_id=self._supplier_id,
                delivery_date=self.delivery_date.date().toString("yyyy-MM-dd"),
                notes=self.notes.toPlainText(),
                po_type=po_type,
            )
            if self.on_save:
                self.on_save()
            from views.purchase_orders.po_detail import PODetail
            self.detail_win = PODetail(po_id=po_id, on_save=self.on_save, blank=blank)
            self.detail_win.show()
            self.close()
        except Exception as e:
            show_error(self, "Could not create order.", e)
