import sys
from PyQt6.QtWidgets import QApplication
from database import init_db
from database.migrations import apply_migrations


def main():
    init_db()
    apply_migrations()
    app = QApplication(sys.argv)

    import models.user as user_model
    from views.login_screen import LoginScreen, _SetupPinDialog

    # First run — no PIN set yet, force admin to create one
    if not user_model.has_any_pin_set():
        setup = _SetupPinDialog()
        if setup.exec() != setup.DialogCode.Accepted:
            sys.exit(0)

    # Show login screen
    login_win = [None]
    main_win   = [None]

    def on_login(user):
        from views.main_window import MainWindow
        login_win[0].hide()
        main_win[0] = MainWindow(current_user=user)
        main_win[0].show()

    login_win[0] = LoginScreen(on_login=on_login)
    login_win[0].show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
