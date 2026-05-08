from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QFont
import controllers.dashboard_controller as dash_ctrl
import os
import sys
import importlib.util
import logging
from datetime import date, timedelta


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


def _run_import(parent, paths):
    """
    Shared import logic — used by both HomeScreen and SalesReportView.
    Returns (success: bool, message: str).
    """
    if getattr(sys, "frozen", False):
        script = os.path.join(sys._MEIPASS, "scripts", "import_sales.py")
    else:
        script = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "scripts", "import_sales.py"))

    if not os.path.exists(script):
        return False, f"import_sales.py not found at:\n{script}"

    try:
        spec   = importlib.util.spec_from_file_location("import_sales", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ensure_tables()
        errors = []
        for path in paths:
            try:
                module.import_csv(path)
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        if errors:
            return False, "Some files had errors:\n" + "\n".join(errors)
        return True, f"Imported {len(paths)} file(s) successfully."
    except Exception as e:
        return False, str(e)



class HomeScreen(QWidget):
    def __init__(self, on_navigate=None):
        super().__init__()
        self._on_navigate = on_navigate
        self._flash_state = False
        self._build_ui()
        self._refresh()
        # Auto-refresh every 60 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(60_000)
        # Flash timer for import alert — every 800ms
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._flash_tick)
        self._flash_timer.start(800)

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

        # ── Import Sales section ──────────────────────────────────────
        sep_imp = QFrame(); sep_imp.setFrameShape(QFrame.Shape.HLine)
        sep_imp.setStyleSheet("color: #2a3a4a;")
        root.addWidget(sep_imp)

        import_row = QHBoxLayout()
        import_row.setSpacing(12)

        # Section label + flash asterisk
        import_label_row = QHBoxLayout()
        import_label_row.setSpacing(6)
        imp_lbl = QLabel("Import Sales")
        imp_lbl.setStyleSheet(
            "font-size: 12px; color: #6e7681; letter-spacing: 1px; background: transparent;")
        import_label_row.addWidget(imp_lbl)
        self._flash_lbl = QLabel("✱")
        self._flash_lbl.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #EF9F27; background: transparent;")
        self._flash_lbl.setVisible(False)
        import_label_row.addWidget(self._flash_lbl)
        import_label_row.addStretch()

        import_col = QVBoxLayout()
        import_col.setSpacing(6)
        import_col.addLayout(import_label_row)

        # Last import status label
        self._import_status_lbl = QLabel("Last import: checking…")
        self._import_status_lbl.setStyleSheet(
            "font-size: 12px; color: #8b949e; background: transparent;")
        import_col.addWidget(self._import_status_lbl)
        import_row.addLayout(import_col)

        # Import button
        self._import_btn = QPushButton("⬆  Import Sales")
        self._import_btn.setFixedHeight(40)
        self._import_btn.setStyleSheet("""
            QPushButton {
                background: #2e7d32;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 16px;
            }
            QPushButton:hover { background: #388e3c; }
        """)
        self._import_btn.clicked.connect(self._import_sales)
        import_row.addWidget(self._import_btn)
        import_row.addStretch()
        root.addLayout(import_row)

        # ── Order Today section ───────────────────────────────────────
        sep_ord = QFrame(); sep_ord.setFrameShape(QFrame.Shape.HLine)
        sep_ord.setStyleSheet("color: #2a3a4a;")
        root.addWidget(sep_ord)

        self._order_today_container = QVBoxLayout()
        self._order_today_container.setSpacing(6)
        root.addLayout(self._order_today_container)

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

    def _flash_tick(self):
        """Toggle the flash asterisk visibility."""
        if self._flash_lbl.isVisible():
            self._flash_state = not self._flash_state
            self._flash_lbl.setStyleSheet(
                f"font-size: 14px; font-weight: bold; background: transparent; "
                f"color: {'#EF9F27' if self._flash_state else '#1a2332'};"
            )

    def _update_import_status(self):
        """Check last import date and update status label and flash indicator."""
        last = dash_ctrl.get_last_import_date()
        yesterday = date.today() - timedelta(days=1)
        today = date.today()

        if last is None:
            self._import_status_lbl.setText("No sales data imported yet")
            self._import_status_lbl.setStyleSheet(
                "font-size: 12px; color: #f85149; background: transparent;")
            self._flash_lbl.setVisible(True)
        elif last < yesterday:
            days_ago = (today - last).days
            self._import_status_lbl.setText(
                f"Last import: {last.strftime('%A, %d %B %Y')}  —  "
                f"{days_ago} day{'s' if days_ago != 1 else ''} ago  ⚠"
            )
            self._import_status_lbl.setStyleSheet(
                "font-size: 12px; color: #EF9F27; background: transparent;")
            self._flash_lbl.setVisible(True)
        else:
            self._import_status_lbl.setText(
                f"Last import: {last.strftime('%A, %d %B %Y')}  ✓")
            self._import_status_lbl.setStyleSheet(
                "font-size: 12px; color: #3fb950; background: transparent;")
            self._flash_lbl.setVisible(False)

    def _import_sales(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Daily PLU Sales File(s)",
            os.path.expanduser("~/Downloads"),
            "CSV Files (*.csv)")
        if not paths:
            return
        success, message = _run_import(self, paths)
        if success:
            QMessageBox.information(self, "Import Complete", message)
            self._refresh()
        else:
            QMessageBox.warning(self, "Import Issue", message)
            self._refresh()

    def _refresh_order_today(self):
        import models.supplier as supplier_model
        from datetime import date as _date

        # Clear previous widgets from the layout
        while self._order_today_container.count():
            item = self._order_today_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            due = supplier_model.get_order_due_today()
        except Exception:
            return

        today_name = _date.today().strftime('%A')
        header = QLabel(f"Orders Due Today  —  {today_name}")
        header.setStyleSheet(
            "font-size: 12px; color: #6e7681; letter-spacing: 1px; background: transparent;")
        self._order_today_container.addWidget(header)

        if not due:
            none_lbl = QLabel("No orders scheduled for today")
            none_lbl.setStyleSheet("font-size: 12px; color: #8b949e; background: transparent;")
            self._order_today_container.addWidget(none_lbl)
            return

        for supplier in due:
            row = QHBoxLayout()
            row.setSpacing(12)

            name_lbl = QLabel(f"🛒  {supplier['name']}")
            name_lbl.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #e6edf3; background: transparent;")
            row.addWidget(name_lbl)
            row.addStretch()

            po_btn = QPushButton("New PO →")
            po_btn.setFixedHeight(30)
            po_btn.setStyleSheet(
                "QPushButton{background:#1565c0;color:white;border:none;"
                "border-radius:4px;padding:0 14px;font-weight:bold;font-size:12px;}"
                "QPushButton:hover{background:#1976d2;}")
            sid = supplier['id']
            po_btn.clicked.connect(lambda _, s=sid: self._new_po_for(s))
            row.addWidget(po_btn)

            frame = QFrame()
            frame.setStyleSheet(
                "QFrame{background:#1e2a38;border-radius:6px;"
                "border-left:4px solid #1565c0;}")
            frame_layout = QHBoxLayout(frame)
            frame_layout.setContentsMargins(12, 6, 12, 6)
            frame_layout.addLayout(row)
            self._order_today_container.addWidget(frame)

    def _new_po_for(self, supplier_id):
        from views.purchase_orders.po_create import POCreate
        self._po_create_win = POCreate(on_save=self._refresh, supplier_id=supplier_id)
        self._po_create_win.show()

    def _refresh(self):
        try:
            stats = dash_ctrl.get_dashboard_stats()
            self._store_lbl.setText(stats['store_name'])
            self._val_sales.setText(f"${stats['today_sales']:,.2f}")
            self._val_pos.setText(str(stats['open_po_count']))
            self._val_low.setText(str(stats['low_stock_count']))
            self._val_products.setText(f"{stats['active_product_count']:,}")
            low_color = "#f85149" if stats['low_stock_count'] > 0 else "#FF9800"
            self._card_low.setStyleSheet(f"""
                QFrame {{
                    background: #1e2a38;
                    border-radius: 10px;
                    border-left: 4px solid {low_color};
                }}
            """)
        except Exception as e:
            logging.warning("HomeScreen refresh error: %s", e, exc_info=True)

        self._update_import_status()
        self._refresh_order_today()
