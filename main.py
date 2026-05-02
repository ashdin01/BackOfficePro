import sys
import os
import traceback
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

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
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
            msg.setDetailedText(
                "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            )
            msg.setInformativeText(f"Log saved to:\n{LOG_FILE}")
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
    """Start the Flask REST API in a background daemon thread."""
    import threading
    def _run():
        try:
            from api_server import app as flask_app
            logging.info("API server starting on 0.0.0.0:5050")
            flask_app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False)
        except OSError as e:
            logging.warning(f"API server could not start (port already in use?): {e}")
        except Exception as e:
            logging.error(f"API server crashed: {e}", exc_info=True)
    t = threading.Thread(target=_run, daemon=True, name="api-server")
    t.start()


def main():
    logging.info("main() called")
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    _init_db_with_lock_recovery(app)
    _start_api_server()

    import models.user as user_model
    from views.login_screen import LoginScreen, _SetupPinDialog
    if not user_model.has_any_pin_set():
        setup = _SetupPinDialog()
        if setup.exec() != setup.DialogCode.Accepted:
            sys.exit(0)
    login_win = [None]
    main_win   = [None]
    def on_login(user):
        logging.info(f"Login successful: {user.get('username')} ({user.get('role')})")
        from views.main_window import MainWindow
        login_win[0].hide()
        main_win[0] = MainWindow(current_user=user)
        main_win[0].show()
    login_win[0] = LoginScreen(on_login=on_login)
    login_win[0].show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
