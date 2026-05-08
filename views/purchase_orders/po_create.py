from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QDateEdit,
    QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox,
    QTextEdit, QLabel, QLineEdit, QDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame
)
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from utils.error_dialog import show_error
import models.purchase_order as po_model
import models.supplier as supplier_model
from config.constants import PO_TYPES, PO_TYPE_PO


class _TypeLookup(QDialog):
    """F2 popup for selecting order type."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Order Type")
        self.setModal(True)
        self.setFixedWidth(360)
        self.setStyleSheet(
            "QDialog{background:#1a2332;color:#e6edf3;}"
            "QTableWidget{background:#1e2a38;color:#e6edf3;"
            "gridline-color:#2a3a4a;border:1px solid #2a3a4a;}"
            "QTableWidget::item:selected{background:#1565c0;}"
            "QHeaderView::section{background:#1e2a38;color:#8b949e;"
            "border:none;padding:4px 8px;font-weight:bold;}"
        )
        self.selected_code = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lbl = QLabel("Double-click or press Enter to select:")
        lbl.setStyleSheet("color:#8b949e; font-size:11px;")
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
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:6px 16px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}")
        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setStyleSheet(
            "QPushButton{background:transparent;color:#8b949e;"
            "border:1px solid #2a3a4a;border-radius:4px;padding:6px 14px;}"
            "QPushButton:hover{background:#1e2a38;color:#e6edf3;}")
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


class POCreate(QWidget):
    def __init__(self, on_save=None):
        super().__init__()
        self.setWindowTitle("New Purchase Order")
        self.setMinimumWidth(440)
        self.on_save = on_save
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
            "QLineEdit{font-weight:bold;font-size:14px;text-transform:uppercase;"
            "background:#1e2a38;color:#4CAF50;border:1px solid #2a3a4a;"
            "border-radius:4px;padding:2px 6px;}"
            "QLineEdit:focus{border-color:#4CAF50;}")

        f2_btn = QPushButton("F2")
        f2_btn.setFixedHeight(32)
        f2_btn.setFixedWidth(34)
        f2_btn.setStyleSheet(
            "QPushButton{background:#1e2a38;color:#8b949e;"
            "border:1px solid #2a3a4a;border-radius:4px;font-size:10px;}"
            "QPushButton:hover{color:#e6edf3;border-color:#8b949e;}")
        f2_btn.clicked.connect(self._type_lookup)

        self.type_desc_lbl = QLabel(PO_TYPES[PO_TYPE_PO])
        self.type_desc_lbl.setStyleSheet("color:#8b949e; font-size:11px;")

        type_row.addWidget(self.type_input)
        type_row.addWidget(f2_btn)
        type_row.addWidget(self.type_desc_lbl)
        type_row.addStretch()

        type_container = QWidget()
        type_container.setLayout(type_row)
        form.addRow("Order Type", type_container)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#2a3a4a;")

        self.supplier = QComboBox()
        suppliers = supplier_model.get_all()
        for s in suppliers:
            self.supplier.addItem(s['name'], s['id'])

        self.delivery_date = QDateEdit()
        self.delivery_date.setCalendarPopup(True)
        self.delivery_date.setDate(QDate.currentDate().addDays(7))
        self.delivery_date.setDisplayFormat("dd/MM/yyyy")

        self.notes = QTextEdit()
        self.notes.setMaximumHeight(70)
        self.notes.setPlaceholderText("Optional notes...")

        form.addRow(sep)
        form.addRow("Supplier *", self.supplier)
        form.addRow("Expected Date", self.delivery_date)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        layout.addSpacing(8)

        # ── Action buttons ────────────────────────────────────────────
        hint = QLabel("Choose how to start this order:")
        hint.setStyleSheet("color:#8b949e; font-size:11px;")
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.setSpacing(8)

        self.rec_btn = QPushButton("📋  Recommended PO  [Ctrl+R]")
        self.rec_btn.setFixedHeight(38)
        self.rec_btn.setDefault(False)
        self.rec_btn.setAutoDefault(False)
        self.rec_btn.setToolTip("Pre-fill with products below reorder point (Purchase Orders only)")
        self.rec_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;font-weight:bold;padding:0 12px;}"
            "QPushButton:hover{background:#1976d2;}"
            "QPushButton:disabled{background:#1e2a38;color:#555;}")
        self.rec_btn.clicked.connect(lambda: self._save(blank=False))

        blank_btn = QPushButton("➕  Blank Order  [Ctrl+B]")
        blank_btn.setFixedHeight(38)
        blank_btn.setDefault(False)
        blank_btn.setAutoDefault(False)
        blank_btn.setToolTip("Create an empty order — add lines manually")
        blank_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;border:none;"
            "border-radius:4px;font-weight:bold;padding:0 12px;}"
            "QPushButton:hover{background:#388e3c;}")
        blank_btn.clicked.connect(lambda: self._save(blank=True))

        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(38)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.close)

        QShortcut(QKeySequence("F2"),     self, self._type_lookup)
        QShortcut(QKeySequence("Ctrl+R"), self, lambda: self._save(blank=False))
        QShortcut(QKeySequence("Ctrl+B"), self, lambda: self._save(blank=True))
        QShortcut(QKeySequence("Escape"), self, self.close)

        btns.addWidget(self.rec_btn)
        btns.addWidget(blank_btn)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        self.type_input.textChanged.connect(self._on_type_changed)
        self._on_type_changed(PO_TYPE_PO)

    def _type_lookup(self):
        dlg = _TypeLookup(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_code:
            self.type_input.setText(dlg.selected_code)

    def _on_type_changed(self, text):
        code = text.upper().strip()
        desc = PO_TYPES.get(code, '')
        self.type_desc_lbl.setText(desc if desc else "— unknown type")
        self.type_desc_lbl.setStyleSheet(
            f"color:{'#8b949e' if desc else '#f85149'}; font-size:11px;")
        self.type_input.setStyleSheet(
            f"QLineEdit{{font-weight:bold;font-size:14px;"
            f"background:#1e2a38;color:{'#4CAF50' if desc else '#f85149'};"
            f"border:1px solid {'#2a3a4a' if desc else '#f85149'};"
            f"border-radius:4px;padding:2px 6px;}}"
            f"QLineEdit:focus{{border-color:{'#4CAF50' if desc else '#f85149'};}}")
        # Recommended PO only makes sense for normal purchase orders
        self.rec_btn.setEnabled(code == PO_TYPE_PO)

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

        supplier_id = self.supplier.currentData()
        if not supplier_id:
            QMessageBox.warning(self, "Validation", "Please select a supplier.")
            return

        try:
            po_id = po_model.create(
                supplier_id=supplier_id,
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
