import sys
import os
import logging
import glob
from datetime import datetime, timedelta

# ── Log file setup ────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_DIR  = os.path.join(os.path.expanduser("~"), "BackOfficeLogs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"backoffice_{datetime.now().strftime('%Y%m%d')}.log")

_log_level = logging.DEBUG if os.environ.get("BACKOFFICE_DEBUG") else logging.INFO
logging.basicConfig(
    filename=LOG_FILE,
    level=_log_level,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.info(f"BackOfficePro starting — Python {sys.version}")

# Clean up logs older than 7 days
for old_log in glob.glob(os.path.join(LOG_DIR, "backoffice_*.log")):
    try:
        if os.path.getmtime(old_log) < (datetime.now() - timedelta(days=7)).timestamp():
            os.remove(old_log)
    except Exception:
        pass

# ── API subprocess entry-point (frozen builds) ────────────────────────
# In a frozen (PyInstaller) build there is only one executable, so we
# re-invoke it with --api-server-mode to get a separate process for
# Waitress.  Must be checked before any Qt import.
if '--api-server-mode' in sys.argv:
    _api_log = os.path.join(LOG_DIR, f"backoffice_api_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        filename=_api_log, level=_log_level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logging.info("API server process starting (--api-server-mode)")
    from api_server import app as _flask_app, _get_api_key as _init_key
    _init_key()
    if '--no-tls' in sys.argv:
        from waitress import serve as _waitress_serve
        _waitress_serve(_flask_app, host='0.0.0.0', port=5050, threads=4)
    else:
        from utils.tls import serve_tls as _serve_tls
        _serve_tls(_flask_app, host='0.0.0.0', port=5050, threads=4)
    sys.exit(0)

# ── Global exception handler — catches ALL unhandled crashes ─────────
def _handle_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logging.critical("UNHANDLED EXCEPTION", exc_info=(exc_type, exc_value, exc_tb))
    try:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("BackOfficePro — Unexpected Error")
            msg.setText("An unexpected error occurred and the app needs to close.")
            msg.setInformativeText(f"Error details have been saved to the log file:\n{LOG_FILE}")
            msg.exec()
    except Exception:
        pass

sys.excepthook = _handle_exception

# ── Original main.py continues below this line ───────────────────────
from database import init_db
from database.migrations import apply_migrations


def _try_unlock_db():
    """
    Delete stale WAL/SHM sidecar files left behind after a crash.
    Returns (success: bool, message: str).
    """
    from config.settings import DATABASE_PATH
    removed = []
    errors  = []
    for ext in (".db-wal", ".db-shm"):
        path = DATABASE_PATH + ext
        if os.path.exists(path):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
                logging.info(f"Force-unlock: removed {path}")
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
                logging.error(f"Force-unlock: could not remove {path}: {e}")
    if errors:
        return False, "Could not remove:\n" + "\n".join(errors)
    if removed:
        return True, "Removed: " + ", ".join(removed)
    return True, "No WAL/SHM files found — lock may be held by another process."


def _init_db_with_lock_recovery(app):
    """
    Run init_db + apply_migrations.  On a database-locked error, show a
    dialog offering Retry or Force Unlock.  Exits the process if the user
    cancels or unlock fails.
    """
    import sqlite3
    from PyQt6.QtWidgets import QMessageBox, QPushButton

    while True:
        try:
            init_db()
            apply_migrations()
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise

            logging.error(f"Database locked on startup: {e}")

            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Database Locked")
            msg.setText("BackOfficePro cannot open the database — it appears to be locked.")
            msg.setInformativeText(
                "This usually happens when the app crashed and left temporary files behind.\n\n"
                "• Retry — try again (use this if another copy of the app was just closed)\n"
                "• Force Unlock — delete the stale lock files and retry\n"
                "  ⚠  Any data from the last session that was not saved may be lost."
            )
            btn_retry   = msg.addButton("Retry",         QMessageBox.ButtonRole.AcceptRole)
            btn_unlock  = msg.addButton("Force Unlock",  QMessageBox.ButtonRole.DestructiveRole)
            btn_exit    = msg.addButton("Exit",          QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(btn_retry)
            msg.exec()
            clicked = msg.clickedButton()

            if clicked == btn_exit or clicked is None:
                logging.info("User chose Exit on database-locked dialog.")
                sys.exit(1)

            if clicked == btn_unlock:
                ok, detail = _try_unlock_db()
                if not ok:
                    QMessageBox.critical(
                        None, "Unlock Failed",
                        f"Could not remove lock files:\n\n{detail}\n\n"
                        "Close any other programs that may have the database open, "
                        "then restart BackOfficePro."
                    )
                    logging.error(f"Force-unlock failed: {detail}")
                    sys.exit(1)
                logging.info(f"Force-unlock succeeded: {detail}")
            # loop → retry init_db()


def _start_api_server():
    """Start the Flask REST API as a child process.

    Running Waitress in a subprocess rather than a thread means a C-level
    crash or segfault in Waitress cannot kill the Qt UI.  A supervisor
    daemon-thread watches the child and restarts it (up to _MAX_RESTARTS
    times) with exponential back-off.

    Returns the supervisor thread; callers can check is_alive() to see
    whether the API is still managed.  The thread also exposes proc_ref[0]
    so the Qt aboutToQuit hook can send SIGTERM to the child on clean exit.
    """
    import subprocess
    import threading
    import time

    _MAX_RESTARTS = 5
    _BACKOFF_BASE = 5   # seconds; doubles each attempt, capped at 60

    if getattr(sys, 'frozen', False):
        # Single frozen executable — re-invoke with a mode flag
        cmd = [sys.executable, '--api-server-mode']
    else:
        cmd = [sys.executable, os.path.join(BASE_DIR, 'api_server.py')]

    _proc_ref = [None]   # mutable ref so the Qt cleanup hook can terminate the child

    def _supervisor():
        failures = 0
        while True:
            try:
                logging.info("API server subprocess starting: %s", cmd[0])
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                _proc_ref[0] = proc
                _, stderr = proc.communicate()   # blocks until child exits
                _proc_ref[0] = None
                rc = proc.returncode

                if rc == 0:
                    logging.warning("API server exited normally — not restarting")
                    return

                failures += 1
                if stderr:
                    logging.error("API server stderr: %s", stderr[-2000:])
                logging.error(
                    "API server crashed (rc=%d, attempt %d/%d)",
                    rc, failures, _MAX_RESTARTS,
                )
                if failures >= _MAX_RESTARTS:
                    logging.critical(
                        "API server failed %d consecutive times — giving up. "
                        "POS and Android clients will not be able to connect.",
                        _MAX_RESTARTS,
                    )
                    return

                delay = min(_BACKOFF_BASE * (2 ** (failures - 1)), 60)
                logging.info("API server restarting in %ds…", delay)
                time.sleep(delay)

            except Exception:
                logging.error("API supervisor error", exc_info=True)
                return

    t = threading.Thread(target=_supervisor, daemon=True, name="api-supervisor")
    t.proc_ref = _proc_ref
    t.start()
    return t


def _start_atria_sync():
    """Best-effort background catch-up of the last week's ATRIA sales.

    Runs in a daemon thread so a slow or unreachable ATRIA server never
    delays app startup; any failure (missing credentials, network down,
    login rejected) is logged only and never surfaces to the user.
    """
    import threading

    def _run():
        try:
            from scripts.fetch_atria_sales import sync_missing_days
            result = sync_missing_days(days=7)
            if result.get('imported'):
                from utils.stock_events import stock_events
                stock_events.changed.emit()
        except Exception:
            logging.exception("Atria sync thread crashed")

    threading.Thread(target=_run, daemon=True, name="atria-sync").start()


def _pick_store(app):
    """Show a store-selection dialog and patch DATABASE_PATH before DB init."""
    import config.settings as _cfg
    if len(_cfg.STORES) <= 1:
        if _cfg.STORES:
            _cfg.ACTIVE_STORE_NAME = _cfg.STORES[0]['name']
        return

    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QFrame
    from PyQt6.QtCore import Qt
    import config.styles as styles

    chosen = [None]

    dlg = QDialog()
    dlg.setWindowTitle("BackOfficePro — Select Store")
    dlg.setModal(True)
    dlg.setMinimumWidth(300)
    dlg.setStyleSheet(
        f"QDialog{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};}}"
        f"QLabel{{color:{styles.CLR_TEXT};background:transparent;}}"
        f"QPushButton{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};"
        f"border:1px solid {styles.CLR_BORDER};border-radius:6px;"
        "font-size:14px;padding:12px;}}"
        f"QPushButton:hover{{background:{styles.CLR_ACCENT};color:white;"
        f"border-color:{styles.CLR_ACCENT};}}"
    )

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(12)

    title = QLabel("Select Store")
    title.setStyleSheet("font-size:18px;font-weight:bold;")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color:{styles.CLR_BORDER};")
    layout.addWidget(sep)

    for store in _cfg.STORES:
        btn = QPushButton(store['name'])
        btn.clicked.connect(lambda _, s=store: (chosen.__setitem__(0, s), dlg.accept()))
        layout.addWidget(btn)

    if dlg.exec() != QDialog.DialogCode.Accepted or chosen[0] is None:
        sys.exit(0)

    store = chosen[0]
    import database.connection as _db_conn
    new_path = os.path.join(_cfg.DATA_DIR, store['db'])
    _cfg.DATABASE_PATH = new_path
    _cfg.ACTIVE_STORE_NAME = store['name']
    _db_conn.DATABASE_PATH = new_path
    os.environ['BACKOFFICE_PROFILE'] = store['name']
    logging.info("Store selected: %s → %s", store['name'], new_path)


def _init_all_stores(app):
    """Run init_db + migrations against every configured store's database,
    used by the merged cross-store login flow (see config.app_config) where
    no single store is "active" until a user actually logs in."""
    import config.settings as _cfg
    import database.connection as _db_conn
    for store in _cfg.STORES:
        path = os.path.join(_cfg.DATA_DIR, store['db'])
        _cfg.DATABASE_PATH = path
        _db_conn.DATABASE_PATH = path
        _cfg.ACTIVE_STORE_NAME = store['name']
        logging.info("Initializing store database: %s -> %s", store['name'], path)
        _init_db_with_lock_recovery(app)

    # Leave a safe default active until login_screen switches it to whichever
    # store the logged-in user actually belongs to.
    if _cfg.STORES:
        first = _cfg.STORES[0]
        path = os.path.join(_cfg.DATA_DIR, first['db'])
        _cfg.DATABASE_PATH = path
        _db_conn.DATABASE_PATH = path
        _cfg.ACTIVE_STORE_NAME = first['name']


def _any_pin_set_anywhere() -> bool:
    """Like models.user.has_any_pin_set(), but checks every store's database
    rather than just the currently active one."""
    import config.settings as _cfg
    import database.connection as _db_conn
    import models.user as user_model

    for store in _cfg.STORES:
        path = os.path.join(_cfg.DATA_DIR, store['db'])
        _cfg.DATABASE_PATH = path
        _db_conn.DATABASE_PATH = path
        if user_model.has_any_pin_set():
            return True
    return False


def _configure_app_icon(app):
    """Set the application window icon so it appears in the taskbar."""
    from PyQt6.QtGui import QIcon
    icon_path = os.path.join(BASE_DIR, 'assets', 'icon.ico')
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        logging.info("App icon set from %s", icon_path)
    else:
        logging.warning("App icon not found: %s", icon_path)


def _set_windows_dark_titlebar(widget):
    """Ask DWM to draw this window's native title bar in dark mode.

    Fusion + stylesheets only theme widget content; the title bar/frame is
    drawn by the Windows compositor and otherwise follows the OS light/dark
    setting regardless of the app's own style.
    """
    import ctypes
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 = Win10 20H1+/Win11, 19 = older Win10
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        logging.exception("Failed to set dark title bar for window")


def _configure_app_style(app):
    """Force a consistent cross-platform Qt style.

    Without this, Qt falls back to each OS's native default style —
    "windowsvista"/"windows11" on Windows, "Fusion" on most Linux setups —
    and since the app's dark theme is applied entirely via stylesheets
    rather than a QPalette, the native Windows style resists it in places,
    leaking through as light mode. Fusion is fully stylesheet-driven and
    renders identically on every OS.
    """
    app.setStyle("Fusion")
    logging.info("App style set to Fusion")

    if sys.platform == "win32":
        from PyQt6.QtCore import QObject, QEvent
        from PyQt6.QtWidgets import QWidget

        class _DarkTitleBarFilter(QObject):
            """Applies a dark title bar to every top-level window as it's shown."""
            def eventFilter(self, obj, event):
                if (event.type() == QEvent.Type.Show
                        and isinstance(obj, QWidget) and obj.isWindow()):
                    _set_windows_dark_titlebar(obj)
                return False

        app._dark_titlebar_filter = _DarkTitleBarFilter(app)
        app.installEventFilter(app._dark_titlebar_filter)
        logging.info("Windows dark title bar event filter installed")


def main():
    logging.info("main() called")
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    _configure_app_style(app)
    _configure_app_icon(app)

    import config.settings as _cfg
    import config.app_config as _app_cfg
    merged_login = _app_cfg.get_merged_login() and len(_cfg.STORES) > 1

    if merged_login:
        _init_all_stores(app)
    else:
        _pick_store(app)
        _init_db_with_lock_recovery(app)

    api_thread = _start_api_server()

    def _stop_api():
        import subprocess
        proc = api_thread.proc_ref[0]
        if proc and proc.poll() is None:
            logging.info("Terminating API server subprocess (pid=%d)", proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    app.aboutToQuit.connect(_stop_api)

    import models.user as user_model
    from views.login_screen import LoginScreen, _SetupPinDialog

    any_pin = _any_pin_set_anywhere() if merged_login else user_model.has_any_pin_set()
    if not any_pin:
        setup = _SetupPinDialog()
        if setup.exec() != setup.DialogCode.Accepted:
            sys.exit(0)
    login_win = [None]
    main_win   = [None]
    def on_login(user):
        logging.info(f"Login successful: {user.get('username')} ({user.get('role')})")
        from database.audit_context import set_context
        set_context(user.get('username', ''), 'UI')
        _start_atria_sync()
        from views.main_window import MainWindow
        login_win[0].hide()
        main_win[0] = MainWindow(current_user=user, api_thread=api_thread)
        main_win[0].show()
    login_win[0] = LoginScreen(on_login=on_login, merged=merged_login)
    login_win[0].show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
