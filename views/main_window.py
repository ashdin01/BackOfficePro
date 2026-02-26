from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame
)
from PyQt6.QtCore import Qt
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
        sidebar.setObjectName("sidebar")
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
            ("Products",        self._show_products),
            ("Suppliers",       self._show_suppliers),
            ("Departments",     self._show_departments),
            ("Purchase Orders", self._show_purchase_orders),
            ("Reports",         self._show_reports),
        ]
        for label, handler in nav_items:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            btn.setCheckable(True)
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()
        main_layout.addWidget(sidebar)

        # ── Content area ─────────────────────────────────
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        # Load all screens into the stack
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

        # Start on Products
        self._switch(0)

    def _switch(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    def _show_products(self):        self._switch(0)
    def _show_suppliers(self):       self._switch(1)
    def _show_departments(self):     self._switch(2)
    def _show_purchase_orders(self): self._switch(3)
    def _show_reports(self):         self._switch(4)
