from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QFont
from database.connection import get_connection


def _stat(label, value, color="#2196F3", sub=None):
    """Create a stat card widget."""
    frame = QFrame()
    frame.setStyleSheet(f"""
        QFrame {{
            background: #1e2a38;
            border-radius: 10px;
            border-left: 4px solid {color};
        }}
    """)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(4)

    val_lbl = QLabel(value)
    val_lbl.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color}; background: transparent;")
    lay.addWidget(val_lbl)

    lbl_lbl = QLabel(label)
    lbl_lbl.setStyleSheet("font-size: 12px; color: #8b949e; background: transparent;")
    lay.addWidget(lbl_lbl)

    if sub:
        sub_lbl = QLabel(sub)
        sub_lbl.setStyleSheet("font-size: 10px; color: #6e7681; background: transparent;")
        lay.addWidget(sub_lbl)

    return frame, val_lbl, lbl_lbl


class HomeScreen(QWidget):
    def __init__(self, on_navigate=None):
        super().__init__()
        self._on_navigate = on_navigate   # callback(index) to switch screens
        self._build_ui()
        self._refresh()

        # Auto-refresh every 60 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(60_000)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()

    def _build_ui(self):
        self.setStyleSheet("QWidget { background: #1a2332; color: #e6edf3; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(28)

        # ── Store name + clock ────────────────────────────────────────
        top = QHBoxLayout()

        store_col = QVBoxLayout()
        self._store_lbl = QLabel("Loading…")
        self._store_lbl.setStyleSheet(
            "font-size: 32px; font-weight: bold; color: #e6edf3; background: transparent;")
        store_col.addWidget(self._store_lbl)

        self._date_lbl = QLabel()
        self._date_lbl.setStyleSheet(
            "font-size: 14px; color: #8b949e; background: transparent;")
        store_col.addWidget(self._date_lbl)
        top.addLayout(store_col)
        top.addStretch()

        self._clock_lbl = QLabel()
        self._clock_lbl.setStyleSheet(
            "font-size: 42px; font-weight: bold; color: #3fb950; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(self._clock_lbl)
        root.addLayout(top)

        # Divider
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a3a4a;")
        root.addWidget(sep)

        # ── Stat cards row ────────────────────────────────────────────
        cards = QHBoxLayout(); cards.setSpacing(16)

        self._card_sales, self._val_sales, _ = _stat(
            "Today's Sales", "$0.00", "#4CAF50")
        self._card_pos, self._val_pos, _ = _stat(
            "Open Purchase Orders", "0", "#2196F3")
        self._card_low, self._val_low, _ = _stat(
            "Low Stock Items", "0", "#FF9800")
        self._card_products, self._val_products, _ = _stat(
            "Active Products", "0", "#9C27B0")

        for card in [self._card_sales, self._card_pos,
                     self._card_low, self._card_products]:
            cards.addWidget(card)
        root.addLayout(cards)

        # ── Quick nav buttons ─────────────────────────────────────────
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #2a3a4a;")
        root.addWidget(sep2)

        nav_lbl = QLabel("Quick Navigation")
        nav_lbl.setStyleSheet(
            "font-size: 12px; color: #6e7681; letter-spacing: 1px; background: transparent;")
        root.addWidget(nav_lbl)

        nav_row = QHBoxLayout(); nav_row.setSpacing(12)
        nav_items = [
            ("Products  [P]",        1, "#1565c0"),
            ("Suppliers  [S]",       2, "#37474f"),
            ("Purchase Orders  [O]", 4, "#2e7d32"),
            ("Reports  [R]",         5, "#6a1b9a"),
        ]
        for label, idx, color in nav_items:
            btn = QPushButton(label)
            btn.setFixedHeight(40)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: bold;
                    padding: 0 16px;
                }}
                QPushButton:hover {{ opacity: 0.85; background: {color}dd; }}
            """)
            if self._on_navigate:
                btn.clicked.connect(lambda _, i=idx: self._on_navigate(i))
            nav_row.addWidget(btn)
        nav_row.addStretch()
        root.addLayout(nav_row)
        root.addStretch()

        # Clock update every second
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(1000)
        self._tick()

    def _tick(self):
        now = QDateTime.currentDateTime()
        self._clock_lbl.setText(now.toString("hh:mm:ss"))
        self._date_lbl.setText(now.toString("dddd, d MMMM yyyy"))

    def _refresh(self):
        conn = get_connection()
        try:
            # Store name
            row = conn.execute(
                "SELECT value FROM settings WHERE key='store_name'"
            ).fetchone()
            self._store_lbl.setText(row[0] if row and row[0] else "My Supermarket")

            # Today's sales
            today = QDateTime.currentDateTime().toString("yyyy-MM-dd")
            sales = conn.execute(
                "SELECT COALESCE(SUM(sales_dollars),0) FROM sales_daily WHERE sale_date=?",
                (today,)
            ).fetchone()
            self._val_sales.setText(f"${(sales[0] or 0):,.2f}")

            # Open POs (DRAFT or SENT)
            open_pos = conn.execute(
                "SELECT COUNT(*) FROM purchase_orders WHERE status IN ('DRAFT','SENT')"
            ).fetchone()
            self._val_pos.setText(str(open_pos[0] or 0))

            # Low stock — active products where on_hand <= reorder_point
            low = conn.execute("""
                SELECT COUNT(*) FROM products p
                LEFT JOIN stock_on_hand s ON s.barcode = p.barcode
                WHERE p.active = 1
                  AND p.reorder_point > 0
                  AND COALESCE(s.quantity, 0) <= p.reorder_point
            """).fetchone()
            low_count = low[0] or 0
            self._val_low.setText(str(low_count))
            self._card_low.setStyleSheet(f"""
                QFrame {{
                    background: #1e2a38;
                    border-radius: 10px;
                    border-left: 4px solid {"#f85149" if low_count > 0 else "#FF9800"};
                }}
            """)

            # Active products
            prods = conn.execute(
                "SELECT COUNT(*) FROM products WHERE active=1"
            ).fetchone()
            self._val_products.setText(f"{prods[0] or 0:,}")

        except Exception as e:
            print(f"[HomeScreen] refresh error: {e}")
        finally:
            conn.close()
