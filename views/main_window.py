from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from config.settings import APP_NAME, APP_VERSION


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1100, 700)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(180)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 20)
        sidebar_layout.setSpacing(8)

        app_label = QLabel(APP_NAME)
        app_label.setWordWrap(True)
        app_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(app_label)
        sidebar_layout.addSpacing(20)

        self.nav_buttons = []
        nav_items = [
            ("&Products",        0),
            ("&Suppliers",       1),
            ("&Departments",     2),
            ("P&urchase Orders", 3),
            ("&Reports",         4),
        ]
        for label, index in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, i=index: self._switch(i))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        # Hotkey hint label
        hint = QLabel("Hotkeys:\nP · S · D · U · R")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: grey; font-size: 10px;")
        sidebar_layout.addWidget(hint)

        main_layout.addWidget(sidebar)

        # ── Content area ─────────────────────────────────
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        from views.products.product_list import ProductList
        from views.suppliers.supplier_list import SupplierList
        from views.departments.department_list import DepartmentList
        from views.purchase_orders.po_list import POList
        from views.reports.stock_on_hand import StockOnHandReport

        self.screens = [
            ProductList(),
            SupplierList(),
            DepartmentList(),
            POList(),
            StockOnHandReport(),
        ]
        for screen in self.screens:
            self.stack.addWidget(screen)

        # Keyboard shortcuts
        QShortcut(QKeySequence("P"), self, lambda: self._switch(0))
        QShortcut(QKeySequence("S"), self, lambda: self._switch(1))
        QShortcut(QKeySequence("D"), self, lambda: self._switch(2))
        QShortcut(QKeySequence("U"), self, lambda: self._switch(3))
        QShortcut(QKeySequence("R"), self, lambda: self._switch(4))

        self._switch(0)

    def _switch(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
