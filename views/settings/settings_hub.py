"""Settings hub — card grid launcher for all settings screens."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import config.styles as styles


_CARDS = [
    # (icon, title, description, factory_key)
    ("🏬", "Store Details",   "Store name, address, phone, ABN and contact emails",       "StoreDetailsScreen"),
    ("👤", "Users",           "Add, edit, deactivate users and reset PINs",                "UsersScreen"),
    ("📦", "Purchase Orders", "Email config for sending POs and the PO PDF export folder", "PurchaseOrdersScreen"),
    ("💾", "Backup",          "Automatic email backup and local/USB backup folder",        "BackupScreen"),
    ("🔌", "Stocktake / API", "API key for Stocktake App and RetailPOSPro",                "ApiAccessScreen"),
    ("🧮", "Tax Rates",       "Default store-wide GST rate",                               "TaxRatesScreen"),
]

_COLS = 3

_CARD_STYLE = (
    f"QPushButton {{{{background: {styles.CLR_BG_PANEL};"
    f"border: 1px solid {styles.CLR_BORDER};"
    f"border-radius: 8px; color: {styles.CLR_TEXT};"
    "text-align: left; padding: 16px;}}"
    "QPushButton:hover {{background: #253244; border-color: {accent};}}"
    f"QPushButton:pressed {{{{background: {styles.CLR_BG};}}}}"
)


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
    title_lbl.setStyleSheet(f"color: {styles.CLR_TEXT}; background: transparent;")
    lay.addWidget(title_lbl)

    desc_lbl = QLabel(desc)
    desc_lbl.setStyleSheet(f"color: {styles.CLR_MUTED}; font-size: 10px; background: transparent;")
    desc_lbl.setWordWrap(True)
    lay.addWidget(desc_lbl)

    inner.setGeometry(0, 0, btn.width(), btn.height())
    btn.resizeEvent = lambda e, w=inner, b=btn: w.setGeometry(0, 0, b.width(), b.height())
    return btn


_ACCENTS = [
    styles.CLR_ACCENT, styles.CLR_SUCCESS_DARK, styles.CLR_PURPLE_DARK,
    '#e65100', '#00838f', '#ad1457',
]


def _open_settings_screen(key: str, wins: list):
    import importlib

    _FACTORIES = {
        "StoreDetailsScreen":   ("views.settings.settings_store",           "StoreDetailsScreen"),
        "UsersScreen":          ("views.settings.settings_users",           "UsersScreen"),
        "PurchaseOrdersScreen": ("views.settings.settings_purchase_orders", "PurchaseOrdersScreen"),
        "BackupScreen":         ("views.settings.settings_backup",          "BackupScreen"),
        "ApiAccessScreen":      ("views.settings.settings_api",             "ApiAccessScreen"),
        "TaxRatesScreen":       ("views.settings.settings_tax",             "TaxRatesScreen"),
    }

    mod_path, cls_name = _FACTORIES[key]
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    w = cls()
    wins.append(w)
    w.show()
    w.raise_()


class SettingsHub(QWidget):
    """Card-grid launcher for all settings screens."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Settings")
        self.setMinimumWidth(640)
        self._wins: list = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)

        heading = QLabel("Settings")
        h_font = QFont(); h_font.setBold(True); h_font.setPointSize(16)
        heading.setFont(h_font)
        heading.setStyleSheet(f"color: {styles.CLR_TEXT};")
        root.addWidget(heading)

        sub = QLabel("Select a category to open it in a new window.")
        sub.setStyleSheet(f"color: {styles.CLR_MUTED}; font-size: 11px; margin-bottom: 8px;")
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
                on_click=lambda checked=False, k=key: _open_settings_screen(k, self._wins),
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
