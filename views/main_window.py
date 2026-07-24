from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame,
    QFileDialog, QMessageBox, QApplication, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QIcon, QPixmap, QColor
from config.settings import APP_NAME, APP_VERSION
import config.settings as _cfg_settings
import controllers.backup_controller as backup_ctrl
import config.styles as styles
from utils.role_access import user_can_access_screen, staff_allowed_screens
from utils.stock_events import stock_events
import logging
import os
import threading
from datetime import datetime

class MainWindow(QMainWindow):
    def __init__(self, current_user=None, api_thread=None):
        super().__init__()
        self.current_user = current_user or {"username": "admin", "role": "ADMIN", "full_name": "Administrator"}
        self._api_thread = api_thread
        _store = _cfg_settings.ACTIVE_STORE_NAME
        self.setWindowTitle(f"{APP_NAME} — {_store} v{APP_VERSION}" if _store else f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1650, 850)
        self.resize(1700, 900)
        self._build_ui()
        if api_thread is not None:
            self._start_api_watchdog()
        self._run_auto_plu_map()

    def _start_api_watchdog(self):
        """Poll the API server thread every 15 s and update the sidebar badge."""
        self._api_watchdog = QTimer(self)
        self._api_watchdog.timeout.connect(self._update_api_status)
        self._api_watchdog.start(15_000)

    def _update_api_status(self):
        if not hasattr(self, '_api_status_label') or self._api_thread is None:
            return
        if self._api_thread.is_alive():
            self._api_status_label.setText("POS API: online")
            self._api_status_label.setStyleSheet(
                f"color: {styles.CLR_SUCCESS}; font-size: 9px;"
            )
        else:
            self._api_status_label.setText("POS API: offline")
            self._api_status_label.setStyleSheet(
                f"color: {styles.CLR_DANGER}; font-size: 9px;"
            )

    def _run_auto_plu_map(self):
        """Silently auto-map any PLUs that exist in products but are missing from plu_barcode_map."""
        import logging
        try:
            from utils.auto_plu_map import auto_map_plu_barcodes
            result = auto_map_plu_barcodes()
            mapped = result.get("mapped", [])
            if mapped:
                logging.info(f"[startup] Auto-mapped {len(mapped)} PLU(s) to barcodes.")
                try:
                    self.screens[0]._refresh()
                except Exception:
                    logging.exception("[startup] screen refresh after PLU auto-map failed")
        except Exception as e:
            logging.warning(f"[startup] auto_plu_map failed: {e}")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────
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
        self._nav_indices = []
        nav_items = [
            ("&Home",              0),
            ("&Products",          1),
            ("&Suppliers",         2),
            ("&Departments",       3),
            ("Purchase &Orders",   4),
            ("A/Recei&vable",     10),
            ("&Total Sales",      11),
            ("&Reports",           5),
            ("Stockta&ke",         6),
            ("Stock &Adjust",      7),
            ("&Sales",             8),
            ("Bun&dles",           9),
        ]
        _role = self.current_user.get("role", "STAFF")

        from PyQt6.QtWidgets import QScrollArea
        nav_widget = QWidget()
        nav_widget.setStyleSheet("background: transparent;")
        nav_inner = QVBoxLayout(nav_widget)
        nav_inner.setContentsMargins(0, 0, 0, 0)
        nav_inner.setSpacing(8)

        for label, index in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            if not user_can_access_screen(_role, index):
                btn.setEnabled(False)
                btn.setToolTip("Admin access required")
                btn.setStyleSheet(f"color: #444; border-color: {styles.CLR_BORDER};")
            else:
                btn.clicked.connect(lambda _, i=index: self._switch(i))
            nav_inner.addWidget(btn)
            self.nav_buttons.append(btn)
            self._nav_indices.append(index)

        nav_inner.addStretch()

        nav_scroll = QScrollArea()
        nav_scroll.setWidget(nav_widget)
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        nav_scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollBar:vertical { width: 4px; }")
        sidebar_layout.addWidget(nav_scroll, 1)

        # ── Settings button (admin only) ──────────────────────────────
        if _role == "ADMIN":
            settings_btn = QPushButton("⚙  Settings")
            settings_btn.setFixedHeight(34)
            settings_btn.setStyleSheet(
                f"QPushButton{{background:{styles.CLR_BG};border:1px solid {styles.CLR_BORDER};"
                f"border-radius:4px;color:{styles.CLR_MUTED};font-size:11px;}}"
                f"QPushButton:hover{{color:{styles.CLR_TEXT};border-color:{styles.CLR_MUTED};}}"
            )
            settings_btn.clicked.connect(self._open_settings)
            sidebar_layout.addWidget(settings_btn)
            sidebar_layout.addSpacing(4)

        # ── Backup button ─────────────────────────────────────────────
        backup_btn = QPushButton("💾  Backup Data")
        backup_btn.setFixedHeight(34)
        backup_btn.setStyleSheet(
            f"QPushButton{{background:#1a3a2a;border:1px solid {styles.CLR_SUCCESS_DARK};"
            f"border-radius:4px;color:{styles.CLR_SUCCESS_ALT};font-weight:bold;font-size:11px;}}"
            f"QPushButton:hover{{background:{styles.CLR_SUCCESS_DARK};color:white;}}"
        )
        backup_btn.clicked.connect(self._manual_backup)
        sidebar_layout.addWidget(backup_btn)

        restore_btn = QPushButton("⟳  Restore Backup")
        restore_btn.setFixedHeight(34)
        restore_btn.setStyleSheet(
            f"QPushButton{{background:#1a1a2e;border:1px solid {styles.CLR_ACCENT};"
            f"border-radius:4px;color:{styles.CLR_BLUE_LIGHT};font-weight:bold;font-size:11px;}}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT};color:white;}}"
        )
        restore_btn.clicked.connect(self._restore_backup)
        sidebar_layout.addWidget(restore_btn)

        self.last_backup_label = QLabel("")
        self.last_backup_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_backup_label.setStyleSheet("color: grey; font-size: 9px;")
        self.last_backup_label.setWordWrap(True)
        sidebar_layout.addWidget(self.last_backup_label)
        self._refresh_last_backup_label()

        self._api_status_label = QLabel("")
        self._api_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._api_status_label.setStyleSheet("color: grey; font-size: 9px;")
        sidebar_layout.addWidget(self._api_status_label)
        if getattr(self, '_api_thread', None) is not None:
            self._update_api_status()

        sidebar_layout.addSpacing(8)
        hint = QLabel("Hotkeys (outside text fields):\nH·P·S·D·O·V·R·K·A·L·B")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: grey; font-size: 10px;")
        sidebar_layout.addWidget(hint)

        # Logged-in user display
        sidebar_layout.addSpacing(8)
        user_name = self.current_user.get("full_name") or self.current_user.get("username", "")
        user_role = self.current_user.get("role", "")
        user_lbl = QLabel(f"👤 {user_name}\n{user_role}")
        user_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        user_lbl.setStyleSheet(f"color: {styles.CLR_SUCCESS_ALT}; font-size: 10px;")
        sidebar_layout.addWidget(user_lbl)

        logout_btn = QPushButton("🔒 Lock")
        logout_btn.setFixedHeight(28)
        logout_btn.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_BG};color:{styles.CLR_MUTED};"
            f"border:1px solid {styles.CLR_BORDER};border-radius:4px;font-size:10px;}}"
            f"QPushButton:hover{{color:{styles.CLR_TEXT};border-color:{styles.CLR_MUTED};}}")
        logout_btn.clicked.connect(self._lock)
        sidebar_layout.addWidget(logout_btn)

        main_layout.addWidget(sidebar)

        # ── Main stack ────────────────────────────────────────────────
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        import logging
        from views.home_screen import HomeScreen
        from views.products.product_list import ProductList
        from views.suppliers.supplier_list import SupplierList
        from views.departments.department_list import DepartmentList
        from views.purchase_orders.po_list import POList
        from views.reports.reports_hub import ReportsHub
        from views.stocktake.stocktake_list import StocktakeList
        from views.stock_adjust.stock_adjust_view import StockAdjustView
        from views.reports.sales_report_view import SalesReportView
        from views.bundles.bundle_list import BundleList
        from views.ar.invoice_list import InvoiceList
        from views.reports.total_sales_report import TotalSalesReport

        screen_classes = [
            ("HomeScreen",        lambda: HomeScreen(on_navigate=self._switch)),
            ("ProductList",       lambda: ProductList(on_escape=lambda: self._switch(0), current_user=self.current_user)),
            ("SupplierList",      lambda: SupplierList(current_user=self.current_user)),
            ("DepartmentList",    lambda: DepartmentList()),
            ("POList",            lambda: POList()),
            ("ReportsHub",        lambda: ReportsHub()),
            ("StocktakeList",     lambda: StocktakeList()),
            ("StockAdjustView",   lambda: StockAdjustView(current_user=self.current_user)),
            ("SalesReportView",   lambda: SalesReportView()),
            ("BundleList",        lambda: BundleList()),
            ("InvoiceList",       lambda: InvoiceList()),
            ("TotalSalesReport",  lambda: TotalSalesReport()),
        ]

        self.screens = []
        for name, factory in screen_classes:
            logging.info(f"Initialising screen: {name}")
            try:
                screen = factory()
                self.screens.append(screen)
                logging.info(f"  {name} OK")
            except Exception as e:
                logging.critical(f"  {name} FAILED: {e}", exc_info=True)
                raise

        for screen in self.screens:
            self.stack.addWidget(screen)

        # ── Refresh all affected screens whenever stock changes anywhere ──
        # (manual adjustment, PO receipt, credit return, stocktake apply,
        # ATRIA import) — see utils/stock_events.py.
        # stock_events is a persistent singleton but _build_ui() re-runs on
        # every lock/relogin cycle on this same instance, so disconnect any
        # prior binding first to avoid stacking duplicate connections.
        try:
            stock_events.changed.disconnect(self._on_stock_changed)
        except TypeError:
            pass
        stock_events.changed.connect(self._on_stock_changed)

        # Single-key nav is handled in keyPressEvent so it only fires when
        # focus is NOT on a text input field.

        self._switch(0)

    def _open_settings(self):
        if self.current_user.get("role") != "ADMIN":
            return
        from views.settings.settings_hub import SettingsHub
        self._settings_win = SettingsHub()
        self._settings_win.show()

    def _lock(self):
        """Lock the app and return to login screen."""
        from views.login_screen import LoginScreen
        self.hide()

        def on_relogin(user):
            from database.audit_context import set_context
            set_context(user.get('username', ''), 'UI')
            login_win.hide()
            self.current_user = user
            # Stop timers on the HomeScreen before the widget is replaced,
            # so they don't fire after the old screen is orphaned.
            if hasattr(self, 'screens') and self.screens:
                home = self.screens[0]
                for attr in ('_timer', '_flash_timer', '_clock_timer'):
                    t = getattr(home, attr, None)
                    if t is not None:
                        t.stop()
            self._build_ui()
            self.show()

        login_win = LoginScreen(on_login=on_relogin)
        login_win.show()

    def _on_stock_changed(self):
        """Refresh all screens that display stock on hand."""
        import logging
        logging.info("stock_changed signal received — refreshing screens")
        # HomeScreen
        try:
            self.screens[0]._refresh()
        except Exception as e:
            logging.warning(f"HomeScreen refresh failed: {e}")
        # ProductList
        try:
            self.screens[1]._load()
        except Exception as e:
            logging.warning(f"ProductList refresh failed: {e}")
        # ReportsHub (index 5) — reports open as separate windows, nothing to refresh here

    def _can_access(self, index: int) -> bool:
        role = self.current_user.get("role", "STAFF")
        return user_can_access_screen(role, index)

    def _switch(self, index):
        if not self._can_access(index):
            return
        self.stack.setCurrentIndex(index)
        for btn, screen_idx in zip(self.nav_buttons, self._nav_indices):
            btn.setChecked(screen_idx == index)

    def keyPressEvent(self, event):
        from PyQt6.QtWidgets import QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox
        # Don't intercept keys while the user is typing in an input widget.
        if isinstance(self.focusWidget(), (QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox)):
            super().keyPressEvent(event)
            return
        nav = {
            Qt.Key.Key_H:      0,
            Qt.Key.Key_P:      1,
            Qt.Key.Key_S:      2,
            Qt.Key.Key_D:      3,
            Qt.Key.Key_O:      4,
            Qt.Key.Key_R:      5,
            Qt.Key.Key_K:      6,
            Qt.Key.Key_A:      7,
            Qt.Key.Key_L:      8,
            Qt.Key.Key_B:      9,
            Qt.Key.Key_V:     10,
            Qt.Key.Key_T:     11,
            Qt.Key.Key_Escape: 0,
        }
        if event.key() in nav:
            self._switch(nav[event.key()])
        else:
            super().keyPressEvent(event)

    # ── Backup logic ──────────────────────────────────────────────────
    def _auto_backup_dir(self):
        return backup_ctrl.get_backup_dir()

    def _refresh_last_backup_label(self):
        dt = backup_ctrl.get_last_backup_time()
        if dt:
            self.last_backup_label.setText(f"Last backup:\n{dt.strftime('%d/%m %H:%M')}")
        else:
            self.last_backup_label.setText("No backups yet")

    def _silent_auto_backup(self):
        dest = backup_ctrl.silent_auto_backup()
        if backup_ctrl.get_backup_local_path():
            ok, msg = backup_ctrl.backup_to_local_path()
            if ok:
                logging.info("Extra local backup written: %s", msg.replace("\n", " "))
            else:
                # Never block app close on this — the drive may simply be unplugged.
                logging.warning("Extra local backup failed: %s", msg.replace("\n", " "))
        if dest:
            return self._email_backup_async(dest)
        return None

    def _email_backup_async(self, backup_path):
        to_address = backup_ctrl.get_backup_email()
        logging.info(f"Backup email: to_address='{to_address}', path='{backup_path}'")
        if not to_address:
            logging.warning("Backup email: backup_email setting is empty — skipping.")
            return None

        def _send():
            logging.info(f"Backup email thread: starting send to {to_address}")
            try:
                from utils.email_graph import send_backup
                send_backup(backup_path, to_address)
                logging.info(f"Backup email thread: sent successfully to {to_address}")
            except ImportError as e:
                logging.error(
                    f"Backup email thread: email library unavailable ({e}). "
                    "Ensure 'msal' is installed: pip install msal"
                )
            except RuntimeError as e:
                logging.error(
                    f"Backup email thread: configuration error — {e}. "
                    "Check Email Configuration in Settings."
                )
            except Exception as e:
                logging.error(f"Backup email thread: send failed: {e}", exc_info=True)

        t = threading.Thread(target=_send, daemon=True)
        t.start()
        logging.info("Backup email thread: started")
        return t

    def _manual_backup(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_dir = backup_ctrl.get_backup_dir()
        os.makedirs(default_dir, exist_ok=True)
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Save Backup",
            os.path.join(default_dir, f"supermarket_{ts}.db"),
            "Database Files (*.db);;All Files (*)"
        )
        if not dest:
            return
        ok, msg = backup_ctrl.do_backup(dest)
        if ok:
            QMessageBox.information(self, "Backup Complete", msg)
            self._refresh_last_backup_label()
        else:
            QMessageBox.critical(self, "Backup Failed", f"Could not save backup:\n\n{msg}")

    def _restore_backup(self):
        src_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Backup to Restore",
            self._auto_backup_dir(),
            "Database Files (*.db);;All Files (*)"
        )
        if not src_path:
            return
        try:
            valid, missing = backup_ctrl.validate_backup_file(src_path)
        except RuntimeError as e:
            logging.warning("Backup file validation failed: %s", e)
            QMessageBox.critical(self, "Invalid File", str(e))
            return
        if not valid:
            QMessageBox.critical(
                self, "Invalid Backup",
                f"This file does not appear to be a valid BackOfficePro database.\n\n"
                f"Missing tables: {', '.join(missing)}"
            )
            return
        reply = QMessageBox.warning(
            self, "Restore Backup",
            f"This will REPLACE your current data with the selected backup:\n\n"
            f"{os.path.basename(src_path)}\n\n"
            f"Your current data will be automatically backed up first.\n\n"
            f"The app will need to restart after restoring.\n\n"
            f"Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_dest = os.path.join(
            self._auto_backup_dir(),
            f"supermarket_PRE_RESTORE_{ts}.db"
        )
        ok, msg = backup_ctrl.do_backup(safety_dest)
        if not ok:
            reply2 = QMessageBox.warning(
                self, "Safety Backup Failed",
                f"Could not back up current data first:\n{msg}\n\n"
                f"Continue with restore anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply2 != QMessageBox.StandardButton.Yes:
                return
        try:
            backup_ctrl.restore_backup(src_path)
        except Exception as e:
            logging.exception("Database restore failed")
            QMessageBox.critical(self, "Restore Failed", f"Could not restore backup:\n{e}")
            return
        QMessageBox.information(
            self, "Restore Complete",
            f"Backup restored successfully.\n\n"
            f"Your previous data was saved to:\n{safety_dest}\n\n"
            f"Please restart the app now for changes to take effect."
        )

    def closeEvent(self, event):
        event.ignore()
        self.hide()

        def _backup_work():
            try:
                email_thread = self._silent_auto_backup()
                if email_thread is not None:
                    email_thread.join(timeout=30)
            except Exception as e:
                logging.error(f"Backup on close failed: {e}", exc_info=True)

        self._close_worker = threading.Thread(target=_backup_work, daemon=True)
        self._close_worker.start()
        self._close_poll = QTimer(self)
        self._close_poll.timeout.connect(self._on_close_poll)
        self._close_poll.start(200)

    def _on_close_poll(self):
        if not self._close_worker.is_alive():
            self._close_poll.stop()
            QApplication.instance().quit()
