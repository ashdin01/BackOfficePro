from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QComboBox, QMenu, QMessageBox, QTabWidget, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut, QColor
import models.purchase_order as po_model
from config.constants import PO_STATUSES


class POList(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._startup_cleanup()
        self._load()

    def _startup_cleanup(self):
        """Delete old cancelled POs silently on startup."""
        deleted = po_model.cleanup_old_pos()
        if deleted:
            print(f"[PO Cleanup] Removed {deleted} old cancelled PO(s)")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Tabs: Active | Archive ────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                padding: 8px 24px;
                font-size: 12px;
                font-weight: bold;
            }
            QTabBar::tab:selected { color: #4CAF50; border-bottom: 2px solid #4CAF50; }
        """)

        # ── Active tab ────────────────────────────────────────────────
        active_widget = QWidget()
        active_layout = QVBoxLayout(active_widget)
        active_layout.setContentsMargins(12, 12, 12, 8)

        self.active_table = self._make_table()
        self.active_table.doubleClicked.connect(self._open)
        self.active_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.active_table.customContextMenuRequested.connect(self._show_context_menu)
        active_layout.addWidget(self.active_table)

        self.active_status = QLabel("")
        self.active_status.setStyleSheet("color:#aaa; font-size:11px; padding:4px 0;")
        active_layout.addWidget(self.active_status)

        # ── Active bottom buttons ─────────────────────────────────────
        active_btns = QHBoxLayout()
        self.btn_new     = self._btn("＋ New PO  [N]",     "#1565c0", self._create)
        self.btn_open    = self._btn("📋 Open PO  [O]",    "#37474f", self._open)
        self.btn_receive = self._btn("📦 Receive PO  [R]", "#2e7d32", self._open_receive)
        self.btn_cancel  = self._btn("✕ Cancel PO",        "#7f1d1d", self._cancel_po)
        for b in [self.btn_new, self.btn_open, self.btn_receive, self.btn_cancel]:
            active_btns.addWidget(b)
        active_btns.addStretch()
        active_layout.addLayout(active_btns)

        self.tabs.addTab(active_widget, "📋  Active Orders")

        # ── Archive tab ───────────────────────────────────────────────
        archive_widget = QWidget()
        archive_layout = QVBoxLayout(archive_widget)
        archive_layout.setContentsMargins(12, 12, 12, 8)

        # Archive filter
        arch_filter_row = QHBoxLayout()
        arch_filter_row.addWidget(QLabel("Filter:"))
        self.archive_filter = QComboBox()
        self.archive_filter.addItem("All Archived", None)
        self.archive_filter.addItem("Received",    "RECEIVED")
        self.archive_filter.addItem("Cancelled",   "CANCELLED")
        self.archive_filter.currentIndexChanged.connect(self._load_archive)
        arch_filter_row.addWidget(self.archive_filter)
        arch_filter_row.addStretch()
        archive_layout.addLayout(arch_filter_row)

        self.archive_table = self._make_table()
        self.archive_table.doubleClicked.connect(self._open_archive)
        archive_layout.addWidget(self.archive_table)

        self.archive_status = QLabel("")
        self.archive_status.setStyleSheet("color:#aaa; font-size:11px; padding:4px 0;")
        archive_layout.addWidget(self.archive_status)

        # Archive bottom buttons
        archive_btns = QHBoxLayout()
        btn_view_arch = self._btn("📋 View PO", "#37474f", self._open_archive)
        archive_btns.addWidget(btn_view_arch)
        archive_btns.addStretch()
        archive_layout.addLayout(archive_btns)

        self.tabs.addTab(archive_widget, "🗄  Archive")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tabs)

        # ── Hotkeys ───────────────────────────────────────────────────
        QShortcut(QKeySequence("N"), self, self._create)
        QShortcut(QKeySequence("O"), self, self._open)
        QShortcut(QKeySequence("R"), self, self._open_receive)

    def _make_table(self):
        t = QTableWidget()
        t.setColumnCount(6)
        t.setHorizontalHeaderLabels([
            "PO Number", "Supplier", "Status", "Delivery Date", "Created", "Notes"
        ])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setColumnWidth(0, 110)
        t.setColumnWidth(2, 90)
        t.setColumnWidth(3, 110)
        t.setColumnWidth(4, 100)
        return t

    def _btn(self, label, color, slot):
        b = QPushButton(label)
        b.setFixedHeight(34)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {color}; color: white; border: none;
                border-radius: 4px; padding: 0 14px;
                font-weight: bold; font-size: 11px;
            }}
            QPushButton:hover {{ opacity: 0.85; }}
        """)
        b.clicked.connect(slot)
        return b

    def _on_tab_changed(self, idx):
        if idx == 1:
            self._load_archive()

    # ── Data loading ──────────────────────────────────────────────────

    def _load(self):
        rows = po_model.get_all(archived=False)
        self._populate_table(self.active_table, rows)

        # Colour-code status column
        status_colours = {
            'DRAFT':   '#888888',
            'SENT':    '#2196F3',
            'PARTIAL': '#FF9800',
        }
        for r in range(self.active_table.rowCount()):
            status = self.active_table.item(r, 2).text()
            colour = status_colours.get(status, '#888888')
            self.active_table.item(r, 2).setForeground(QColor(colour))

        self.active_status.setText(
            f"{self.active_table.rowCount()} active purchase orders  "
            f"·  Double-click to open  ·  Right-click for options"
        )

    def _load_archive(self):
        status = self.archive_filter.currentData()
        if status:
            rows = po_model.get_all(status=status)
        else:
            rows = po_model.get_all(archived=True)
        self._populate_table(self.archive_table, rows)

        status_colours = {
            'RECEIVED':  '#4CAF50',
            'CANCELLED': '#f44336',
        }
        for r in range(self.archive_table.rowCount()):
            status = self.archive_table.item(r, 2).text()
            colour = status_colours.get(status, '#888888')
            self.archive_table.item(r, 2).setForeground(QColor(colour))

        self.archive_status.setText(
            f"{self.archive_table.rowCount()} archived purchase orders"
        )

    def _populate_table(self, table, rows):
        table.setRowCount(0)
        for row in rows:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(row['po_number']))
            table.setItem(r, 1, QTableWidgetItem(row['supplier_name']))
            table.setItem(r, 2, QTableWidgetItem(row['status']))
            table.setItem(r, 3, QTableWidgetItem(row['delivery_date'] or ''))
            table.setItem(r, 4, QTableWidgetItem(row['created_at'][:10]))
            table.setItem(r, 5, QTableWidgetItem(row['notes'] or ''))
            table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])

    # ── Selection helpers ─────────────────────────────────────────────

    def _get_selected(self, table=None):
        if table is None:
            table = self.active_table
        row = table.currentRow()
        if row < 0:
            return None, None
        po_id  = table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        status = table.item(row, 2).text()
        return po_id, status

    # ── Actions ───────────────────────────────────────────────────────

    def _create(self):
        from views.purchase_orders.po_create import POCreate
        self.create_win = POCreate(on_save=self._load)
        self.create_win.show()

    def _open(self):
        po_id, status = self._get_selected()
        if po_id is None:
            return
        from views.purchase_orders.po_detail import PODetail
        self.detail_win = PODetail(po_id=po_id, on_save=self._load)
        self.detail_win.show()

    def _open_archive(self):
        po_id, status = self._get_selected(self.archive_table)
        if po_id is None:
            return
        from views.purchase_orders.po_history import POHistory
        self.detail_win = POHistory(po_id=po_id)
        self.detail_win.show()

    def _open_receive(self):
        po_id, status = self._get_selected()
        if po_id is None:
            QMessageBox.information(self, "No Selection", "Select a PO first.")
            return
        if status not in ('SENT', 'PARTIAL'):
            QMessageBox.information(
                self, "Cannot Receive",
                "Only SENT or PARTIAL orders can be received."
            )
            return
        from views.purchase_orders.po_receive import POReceive
        self.receive_win = POReceive(po_id=po_id, on_save=self._load)
        self.receive_win.show()

    def _cancel_po(self):
        po_id, status = self._get_selected()
        if po_id is None:
            QMessageBox.information(self, "No Selection", "Select a PO first.")
            return
        if status in ('RECEIVED', 'CANCELLED'):
            QMessageBox.information(self, "Cannot Cancel",
                f"A {status} order cannot be cancelled.")
            return
        po = po_model.get_by_id(po_id)
        reply = QMessageBox.warning(
            self, "Cancel Purchase Order",
            f"Cancel {po['po_number']} — {po['supplier_name']}?\n\n"
            f"Status: {status}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            po_model.cancel(po_id)
            self._load()

    def _show_context_menu(self, pos):
        row = self.active_table.rowAt(pos.y())
        if row < 0:
            return
        self.active_table.selectRow(row)
        po_id, status = self._get_selected()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#1e2a38; border:1px solid #2a3a4a;
                    color:#e6edf3; font-size:12px; padding:4px; }
            QMenu::item { padding:7px 20px; border-radius:4px; }
            QMenu::item:selected { background:#1565c0; }
            QMenu::separator { height:1px; background:#2a3a4a; margin:4px 8px; }
        """)

        act_open = QAction("📋  Open / Edit", self)
        act_open.triggered.connect(self._open)
        menu.addAction(act_open)

        if status in ('SENT', 'PARTIAL'):
            act_recv = QAction("📦  Receive Stock", self)
            act_recv.triggered.connect(self._open_receive)
            menu.addAction(act_recv)

        menu.addSeparator()

        if status not in ('RECEIVED', 'CANCELLED'):
            act_cancel = QAction("✕  Cancel PO", self)
            act_cancel.triggered.connect(self._cancel_po)
            menu.addAction(act_cancel)

        menu.exec(self.active_table.viewport().mapToGlobal(pos))
