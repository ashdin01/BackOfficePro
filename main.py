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

def main():
    logging.info("main() called")
    init_db()
    apply_migrations()
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
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
