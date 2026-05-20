"""Reports hub — card grid launcher for all reports."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


_CARDS = [
    # (icon, title, description, factory_key)
    ("📈", "Sales (POS)",        "Daily POS sales by product and date",           "SalesReportView"),
    ("🧾", "GST / BAS",          "GST collected by period for BAS lodgement",      "GSTReport"),
    ("📊", "Gross Profit",       "GP analysis by product and department",          "GPReport"),
    ("💰", "Stock Valuation",    "Current stock value by department",              "StockValuationReport"),
    ("⚠",  "Reorder",            "Products below reorder point",                   "ReorderReport"),
    ("📋", "Movement History",   "Full stock movement audit log",                  "MovementHistoryReport"),
    ("🏪", "Supplier Sales",     "Sales performance per supplier",                 "SupplierSalesReport"),
    ("🗑",  "Write-Offs",         "Stock write-off history",                        "WriteOffReport"),
    ("🍺", "Liquor Tracking",    "Liquor register compliance report",              "LiquorReport"),
    ("📉", "Aged Debtors",       "Outstanding AR balances by age bracket",         "AgedDebtorsReport"),
    ("🏷",  "PLU Manager",        "Map PLU codes to product barcodes",              "PLUManager"),
]

_COLS = 3

_CARD_STYLE = """
QPushButton {{
    background: #1e2a38;
    border: 1px solid #2a3a4a;
    border-radius: 8px;
    color: #e6edf3;
    text-align: left;
    padding: 16px;
}}
QPushButton:hover {{
    background: #253244;
    border-color: {accent};
}}
QPushButton:pressed {{
    background: #1a2332;
}}
"""


def _make_card(icon: str, title: str, desc: str, accent: str, on_click) -> QPushButton:
    btn = QPushButton()
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setMinimumHeight(90)
    btn.setStyleSheet(_CARD_STYLE.format(accent=accent))
    btn.clicked.connect(on_click)

    # Build the label manually so we can have two lines with different styles
    inner = QWidget(btn)
    inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(4)

    title_lbl = QLabel(f"{icon}  {title}")
    bold = QFont(); bold.setBold(True); bold.setPointSize(11)
    title_lbl.setFont(bold)
    title_lbl.setStyleSheet("color: #e6edf3; background: transparent;")
    lay.addWidget(title_lbl)

    desc_lbl = QLabel(desc)
    desc_lbl.setStyleSheet("color: #8b949e; font-size: 10px; background: transparent;")
    desc_lbl.setWordWrap(True)
    lay.addWidget(desc_lbl)

    inner.setGeometry(0, 0, btn.width(), btn.height())
    btn.resizeEvent = lambda e, w=inner, b=btn: w.setGeometry(0, 0, b.width(), b.height())
    return btn


_ACCENTS = [
    '#1565c0', '#2e7d32', '#6a1b9a', '#c62828',
    '#e65100', '#00838f', '#4527a0', '#558b2f',
    '#ad1457', '#4e342e', '#37474f', '#f57f17',
]


def _open_report(key: str, wins: list):
    import importlib

    _FACTORIES = {
        "SalesReportView":    ("views.reports.sales_report_view",   "SalesReportView"),
        "GSTReport":          ("views.reports.gst_report",          "GSTReport"),
        "GPReport":           ("views.reports.gp_report",           "GPReport"),
        "StockValuationReport": ("views.reports.stock_valuation",   "StockValuationReport"),
        "ReorderReport":      ("views.reports.reorder_report",      "ReorderReport"),
        "MovementHistoryReport": ("views.reports.movement_history", "MovementHistoryReport"),
        "SupplierSalesReport": ("views.reports.supplier_sales_report", "SupplierSalesReport"),
        "WriteOffReport":     ("views.reports.writeoff_report",     "WriteOffReport"),
        "LiquorReport":       ("views.reports.liquor_report",       "LiquorReport"),
        "AgedDebtorsReport":  ("views.ar.aged_debtors",             "AgedDebtorsReport"),
        "PLUManager":         ("views.products.plu_manager",        "PLUManager"),
    }

    mod_path, cls_name = _FACTORIES[key]
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    w = cls()
    wins.append(w)
    w.show()
    w.raise_()


class ReportsHub(QWidget):
    """Card-grid launcher for all report screens."""

    def __init__(self):
        super().__init__()
        self._wins: list = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)

        heading = QLabel("Reports")
        h_font = QFont(); h_font.setBold(True); h_font.setPointSize(16)
        heading.setFont(h_font)
        heading.setStyleSheet("color: #e6edf3;")
        root.addWidget(heading)

        sub = QLabel("Select a report to open it in a new window.")
        sub.setStyleSheet("color: #8b949e; font-size: 11px; margin-bottom: 8px;")
        root.addWidget(sub)

        # scroll area so hub works at any window height
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        root.addWidget(scroll)

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_widget)
        grid.setSpacing(12)

        for i, (icon, title, desc, key) in enumerate(_CARDS):
            accent = _ACCENTS[i % len(_ACCENTS)]
            card = _make_card(
                icon, title, desc, accent,
                on_click=lambda checked=False, k=key: _open_report(k, self._wins),
            )
            grid.addWidget(card, i // _COLS, i % _COLS)

        # fill empty cells in last row so columns stay even
        remainder = len(_CARDS) % _COLS
        if remainder:
            for col in range(remainder, _COLS):
                placeholder = QWidget()
                grid.addWidget(placeholder, len(_CARDS) // _COLS, col)

        grid.setRowStretch(grid.rowCount(), 1)
        scroll.setWidget(grid_widget)
