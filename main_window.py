from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame,
    QFileDialog, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from config.settings import APP_NAME, APP_VERSION, DATABASE_PATH
import logging
import shutil
import os
import threading
from datetime import datetime

def _do_backup(dest_path):
    """Copy the live DB to dest_path. Returns (success, message)."""
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(DATABASE_PATH, dest_path)
        size = os.path.getsize(dest_path)
        return True, f"Backup saved:\n{dest_path}\n({size/1024:.1f} KB)"
    except Exception as e:
        return False, str(e)

class MainWindow(QMainWindow):
    def __init__(self, current_user=None):
        super().__init__()
        self.current_user = current_user or {"username": "admin", "role": "ADMIN", "full_name": "Administrator"}
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1400, 850)
        self._build_ui()

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
        nav_items = [
            ("&Home",            0),
            ("&Products",        1),
            ("&Suppliers",       2),
            ("&Departments",     3),
            ("Purchase &Orders", 4),
            ("&Reports",         5),
            ("Stockta&ke",       6),
            ("Stock &Adjust",    7),
            ("&Sales",           8),
            ("Bun&dles",         9),
        ]
        is_admin = self.current_user.get("role") in ("ADMIN", "MANAGER")
        # STAFF can only see: Home, Products, Reports, Sales
        staff_allowed = {0, 1, 5, 8}

        # Nav buttons in a scroll area so they're never clipped on small screens
        from PyQt6.QtWidgets import QScrollArea
        nav_widget = QWidget()
        nav_widget.setStyleSheet("background: transparent;")
        nav_inner = QVBoxLayout(nav_widget)
        nav_inner.setContentsMargins(0, 0, 0, 0)
        nav_inner.setSpacing(8)

        for label, index in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            if not is_admin and index not in staff_allowed:
                btn.setEnabled(False)
                btn.setToolTip("Admin access required")
                btn.setStyleSheet("color: #444; border-color: #2a3a4a;")
            else:
                btn.clicked.connect(lambda _, i=index: self._switch(i))
            nav_inner.addWidget(btn)
            self.nav_buttons.append(btn)

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
        if is_admin:
            settings_btn = QPushButton("⚙  Settings")
            settings_btn.setFixedHeight(34)
            settings_btn.setStyleSheet("""
                QPushButton {
                    background: #1a2332;
                    border: 1px solid #2a3a4a;
                    border-radius: 4px;
                    color: #8b949e;
                    font-size: 11px;
                }
                QPushButton:hover { color: #e6edf3; border-color: #8b949e; }
            """)
            settings_btn.clicked.connect(self._open_settings)
            sidebar_layout.addWidget(settings_btn)
            sidebar_layout.addSpacing(4)

        # ── Backup button ─────────────────────────────────────────────
        backup_btn = QPushButton("💾  Backup Data")
        backup_btn.setFixedHeight(34)
        backup_btn.setStyleSheet("""
            QPushButton {
                background: #1a3a2a;
                border: 1px solid #2e7d32;
                border-radius: 4px;
                color: #4CAF50;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background: #2e7d32; color: white; }
        """)
        backup_btn.clicked.connect(self._manual_backup)
        sidebar_layout.addWidget(backup_btn)

        restore_btn = QPushButton("⟳  Restore Backup")
        restore_btn.setFixedHeight(34)
        restore_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a2e;
                border: 1px solid #1565c0;
                border-radius: 4px;
                color: #5c9de8;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background: #1565c0; color: white; }
        """)
        restore_btn.clicked.connect(self._restore_backup)
        sidebar_layout.addWidget(restore_btn)

        self.last_backup_label = QLabel("")
        self.last_backup_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_backup_label.setStyleSheet("color: grey; font-size: 9px;")
        self.last_backup_label.setWordWrap(True)
        sidebar_layout.addWidget(self.last_backup_label)
        self._refresh_last_backup_label()

        sidebar_layout.addSpacing(8)
        hint = QLabel("Hotkeys:\nH·P·S·D·O·R·K·A·L")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: grey; font-size: 10px;")
        sidebar_layout.addWidget(hint)

        # Logged-in user display
        sidebar_layout.addSpacing(8)
        user_name = self.current_user.get("full_name") or self.current_user.get("username", "")
        user_role = self.current_user.get("role", "")
        user_lbl = QLabel(f"👤 {user_name}\n{user_role}")
        user_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        user_lbl.setStyleSheet("color: #4CAF50; font-size: 10px;")
        sidebar_layout.addWidget(user_lbl)

        logout_btn = QPushButton("🔒 Lock")
        logout_btn.setFixedHeight(28)
        logout_btn.setStyleSheet(
            "QPushButton{background:#1a2332;color:#8b949e;border:1px solid #2a3a4a;"
            "border-radius:4px;font-size:10px;}"
            "QPushButton:hover{color:#e6edf3;border-color:#8b949e;}")
        logout_btn.clicked.connect(self._lock)
        sidebar_layout.addWidget(logout_btn)

        main_layout.addWidget(sidebar)

        # ── Main stack ────────────────────────────────────────────────
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        from views.home_screen import HomeScreen
        from views.products.product_list import ProductList
        from views.suppliers.supplier_list import SupplierList
        from views.departments.department_list import DepartmentList
        from views.purchase_orders.po_list import POList
        from views.reports.stock_on_hand import StockOnHandReport
        from views.stocktake.stocktake_list import StocktakeList
        from views.stock_adjust.stock_adjust_view import StockAdjustView
        from views.reports.sales_report_view import SalesReportView
        from views.bundles.bundle_list import BundleList

        self.screens = [
            HomeScreen(on_navigate=self._switch),   # index 0
            ProductList(on_escape=lambda: self._switch(0)),  # index 1
            SupplierList(),                          # index 2
            DepartmentList(),                        # index 3
            POList(),                                # index 4
            StockOnHandReport(),                     # index 5
            StocktakeList(),                         # index 6
            StockAdjustView(current_user=self.current_user),  # index 7
            SalesReportView(),                       # index 8
            BundleList(),                            # index 9
        ]
        for screen in self.screens:
            self.stack.addWidget(screen)

        QShortcut(QKeySequence("H"),      self, lambda: self._switch(0))
        QShortcut(QKeySequence("Escape"), self, lambda: self._switch(0))
        QShortcut(QKeySequence("P"),      self, lambda: self._switch(1))
        QShortcut(QKeySequence("S"),      self, lambda: self._switch(2))
        QShortcut(QKeySequence("D"),      self, lambda: self._switch(3))
        QShortcut(QKeySequence("O"),      self, lambda: self._switch(4))
        QShortcut(QKeySequence("R"),      self, lambda: self._switch(5))
        QShortcut(QKeySequence("K"),      self, lambda: self._switch(6))
        QShortcut(QKeySequence("A"),      self, lambda: self._switch(7))
        QShortcut(QKeySequence("L"),      self, lambda: self._switch(8))

        self._switch(0)

    def _open_settings(self):
        from settings_screen import SettingsScreen
        self._settings_win = SettingsScreen()
        self._settings_win.show()

    def _lock(self):
        """Lock the app and return to login screen."""
        import models.user as user_model
        from views.login_screen import LoginScreen
        self.hide()

        def on_relogin(user):
            login_win.hide()
            self.current_user = user
            # Rebuild UI to apply new user's role
            self._build_ui()
            self.show()

        login_win = LoginScreen(on_login=on_relogin)
        login_win.show()

    def _switch(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    # ── Backup logic ──────────────────────────────────────────────────
    def _auto_backup_dir(self):
        return os.path.join(os.path.expanduser("~"), "BackOfficeBackups")

    def _refresh_last_backup_label(self):
        backup_dir = self._auto_backup_dir()
        try:
            files = sorted(
                [f for f in os.listdir(backup_dir) if f.endswith(".db")],
                reverse=True
            )
            if files:
                ts = files[0].replace("supermarket_", "").replace(".db", "")
                dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
                self.last_backup_label.setText(
                    f"Last backup:\n{dt.strftime('%d/%m %H:%M')}"
                )
            else:
                self.last_backup_label.setText("No backups yet")
        except Exception:
            self.last_backup_label.setText("")

    def _silent_auto_backup(self):
        backup_dir = self._auto_backup_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_dir, f"supermarket_{ts}.db")
        ok, _ = _do_backup(dest)
        if ok:
            try:
                files = sorted(
                    [os.path.join(backup_dir, f)
                     for f in os.listdir(backup_dir) if f.endswith(".db")]
                )
                for old in files[:-30]:
                    os.remove(old)
            except Exception:
                pass
            return self._email_backup_async(dest)
        return None

    def _email_backup_async(self, backup_path):
        from database.connection import get_connection
        try:
            conn = get_connection()
            row = conn.execute("SELECT value FROM settings WHERE key='backup_email'").fetchone()
            conn.close()
            to_address = (row['value'] or '').strip() if row else ''
        except Exception as e:
            logging.error(f"Backup email: failed to read backup_email setting: {e}", exc_info=True)
            return None

        logging.info(f"Backup email: to_address='{to_address}', backup_path='{backup_path}'")
        if not to_address:
            logging.warning("Backup email: backup_email setting is empty — skipping.")
            return None

        from utils.email_graph import send_backup

        def _send():
            logging.info(f"Backup email thread: starting send to {to_address}")
            try:
                send_backup(backup_path, to_address)
                logging.info(f"Backup email thread: sent successfully to {to_address}")
            except Exception as e:
                logging.error(f"Backup email thread: send failed: {e}", exc_info=True)

        t = threading.Thread(target=_send, daemon=True)
        t.start()
        logging.info(f"Backup email thread: started (thread id={t.ident})")
        return t

    def _manual_backup(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"supermarket_{ts}.db"
        default_dir = self._auto_backup_dir()
        os.makedirs(default_dir, exist_ok=True)
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Save Backup",
            os.path.join(default_dir, default_name),
            "Database Files (*.db);;All Files (*)"
        )
        if not dest:
            return
        ok, msg = _do_backup(dest)
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
            import sqlite3
            conn = sqlite3.connect(src_path)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            conn.close()
            required = {"products", "suppliers", "departments", "purchase_orders"}
            missing = required - set(tables)
            if missing:
                QMessageBox.critical(
                    self, "Invalid Backup",
                    f"This file does not appear to be a valid BackOfficePro database.\n\n"
                    f"Missing tables: {', '.join(missing)}"
                )
                return
        except Exception as e:
            QMessageBox.critical(self, "Invalid File", f"Could not read file:\n{e}")
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
        ok, msg = _do_backup(safety_dest)
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
            shutil.copy2(src_path, DATABASE_PATH)
        except Exception as e:
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
