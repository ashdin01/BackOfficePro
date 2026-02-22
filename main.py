import sys
from PyQt6.QtWidgets import QApplication
from database import init_db
from database.migrations import apply_migrations
from views.main_window import MainWindow


def main():
    init_db()
    apply_migrations()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
