from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame,
    QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from config.settings import APP_NAME, APP_VERSION, DATABASE_PATH
import shutil
import os
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
    def __init__(self):
        super().__init__()
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
            ("&Products",        0),
            ("&Suppliers",       1),
            ("&Departments",     2),
            ("Purchase &Orders", 3),
            ("&Reports",         4),
            ("Stockta&ke",       5),
            ("Stock &Adjust",    6),
            ("&Sales",           7),
        ]
        for label, index in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, i=index: self._switch(i))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

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

        # Last backup label
        self.last_backup_label = QLabel("")
        self.last_backup_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_backup_label.setStyleSheet("color: grey; font-size: 9px;")
        self.last_backup_label.setWordWrap(True)
        sidebar_layout.addWidget(self.last_backup_label)
        self._refresh_last_backup_label()

        sidebar_layout.addSpacing(8)
        hint = QLabel("Hotkeys:\nP·S·D·O·R·K·A·L")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: grey; font-size: 10px;")
        sidebar_layout.addWidget(hint)

        main_layout.addWidget(sidebar)

        # ── Main stack ────────────────────────────────────────────────
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        from views.products.product_list import ProductList
        from views.suppliers.supplier_list import SupplierList
        from views.departments.department_list import DepartmentList
        from views.purchase_orders.po_list import POList
        from views.reports.stock_on_hand import StockOnHandReport
        from views.stocktake.stocktake_list import StocktakeList
        from views.stock_adjust.stock_adjust_view import StockAdjustView
        from views.reports.sales_report_view import SalesReportView

        self.screens = [
            ProductList(),
            SupplierList(),
            DepartmentList(),
            POList(),
            StockOnHandReport(),
            StocktakeList(),
            StockAdjustView(),
            SalesReportView(),
        ]
        for screen in self.screens:
            self.stack.addWidget(screen)

        QShortcut(QKeySequence("P"),      self, lambda: self._switch(0))
        QShortcut(QKeySequence("Escape"),  self, lambda: self._switch(0))
        QShortcut(QKeySequence("S"), self, lambda: self._switch(1))
        QShortcut(QKeySequence("D"), self, lambda: self._switch(2))
        QShortcut(QKeySequence("O"), self, lambda: self._switch(3))
        QShortcut(QKeySequence("R"), self, lambda: self._switch(4))
        QShortcut(QKeySequence("K"), self, lambda: self._switch(5))
        QShortcut(QKeySequence("A"), self, lambda: self._switch(6))
        QShortcut(QKeySequence("L"), self, lambda: self._switch(7))

        self._switch(0)

    def _switch(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    # ── Backup logic ──────────────────────────────────────────────────

    def _auto_backup_dir(self):
        return os.path.join(os.path.expanduser("~"), "BackOfficeBackups")

    def _refresh_last_backup_label(self):
        """Show timestamp of most recent auto-backup."""
        backup_dir = self._auto_backup_dir()
        try:
            files = sorted(
                [f for f in os.listdir(backup_dir) if f.endswith(".db")],
                reverse=True
            )
            if files:
                ts = files[0].replace("supermarket_", "").replace(".db", "")
                # Format: 20260319_230000 → 19/03 23:00
                dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
                self.last_backup_label.setText(
                    f"Last backup:\n{dt.strftime('%d/%m %H:%M')}"
                )
            else:
                self.last_backup_label.setText("No backups yet")
        except Exception:
            self.last_backup_label.setText("")

    def _silent_auto_backup(self):
        """Auto-backup to ~/BackOfficeBackups/ on close. Keeps 30 copies."""
        backup_dir = self._auto_backup_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_dir, f"supermarket_{ts}.db")
        ok, msg = _do_backup(dest)
        if ok:
            # Prune — keep last 30
            try:
                files = sorted(
                    [os.path.join(backup_dir, f)
                     for f in os.listdir(backup_dir) if f.endswith(".db")]
                )
                for old in files[:-30]:
                    os.remove(old)
            except Exception:
                pass

    def _manual_backup(self):
        """Let user choose backup destination."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"supermarket_{ts}.db"

        # Default to ~/BackOfficeBackups but user can navigate anywhere
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
        """Let user select a backup file and restore it."""
        src_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Backup to Restore",
            self._auto_backup_dir(),
            "Database Files (*.db);;All Files (*)"
        )
        if not src_path:
            return

        # ── Validate it's a real BackOfficePro database ───────────────
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

        # ── Confirm with user ─────────────────────────────────────────
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

        # ── Auto-backup current DB first ──────────────────────────────
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

        # ── Restore ───────────────────────────────────────────────────
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
        """Auto-backup silently every time the app closes."""
        self._silent_auto_backup()
        event.accept()
