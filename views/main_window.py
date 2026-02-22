from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFrame
)
from PyQt6.QtCore import Qt
from config.settings import APP_NAME, APP_VERSION


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(900, 600)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        buttons = [
            ("Products",        self._open_products),
            ("Suppliers",       self._open_suppliers),
            ("Departments",     self._open_departments),
            ("Purchase Orders", self._open_purchase_orders),
            ("Reports",         self._open_reports),
        ]

        for label, handler in buttons:
            btn = QPushButton(label)
            btn.setFixedWidth(250)
            btn.clicked.connect(handler)
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _open_products(self):
        from views.products.product_list import ProductList
        self._show(ProductList())

    def _open_suppliers(self):
        from views.suppliers.supplier_list import SupplierList
        self._show(SupplierList())

    def _open_departments(self):
        from views.departments.department_list import DepartmentList
        self._show(DepartmentList())

    def _open_purchase_orders(self):
        from views.purchase_orders.po_list import POList
        self._show(POList())

    def _open_reports(self):
        from views.reports.stock_on_hand import StockOnHandReport
        self._show(StockOnHandReport())

    def _show(self, widget):
        widget.setWindowTitle(widget.__class__.__name__)
        widget.show()
