from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QDialog, QFormLayout, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from datetime import datetime, timedelta
import models.user as user_model

_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 30

# Module-level: survives login screen close/reopen within the same app session,
# preventing bypass by dismissing and reopening the widget.
_failed_attempts: dict = {}  # username -> int
_lockout_until: dict = {}    # username -> datetime


class _SetupPinDialog(QDialog):
    """
    First-run dialog — no PINs set yet.
    Forces admin to create a PIN before the app opens.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Up Admin PIN")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setStyleSheet("""
            QDialog  { background: #1a2332; color: #e6edf3; }
            QLabel   { color: #e6edf3; background: transparent; }
            QLineEdit { background: #1e2a38; color: #e6edf3;
                        border: 1px solid #2a3a4a; border-radius: 4px;
                        padding: 6px; font-size: 18px; letter-spacing: 4px; }
            QPushButton { background: #1565c0; color: white; border: none;
                          border-radius: 4px; padding: 8px 20px; font-weight: bold; }
            QPushButton:hover { background: #1976d2; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Welcome to BackOfficePro")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        info = QLabel("No PIN has been set yet.\nCreate a 4-digit PIN for the Admin account to continue.")
        info.setStyleSheet("color: #8b949e; font-size: 12px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a3a4a;")
        layout.addWidget(sep)

        form = QFormLayout()
        form.setSpacing(10)
        self.pin1 = QLineEdit()
        self.pin1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin1.setMaxLength(4)
        self.pin1.setPlaceholderText("••••")
        self.pin2 = QLineEdit()
        self.pin2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin2.setMaxLength(4)
        self.pin2.setPlaceholderText("••••")
        form.addRow("New PIN (4 digits):", self.pin1)
        form.addRow("Confirm PIN:", self.pin2)
        layout.addLayout(form)

        btn = QPushButton("Set PIN & Continue")
        btn.clicked.connect(self._save)
        layout.addWidget(btn)

        self.pin1.returnPressed.connect(lambda: self.pin2.setFocus())
        self.pin2.returnPressed.connect(self._save)
        self.pin1.setFocus()

    def _save(self):
        p1 = self.pin1.text().strip()
        p2 = self.pin2.text().strip()
        if len(p1) != 4 or not p1.isdigit():
            QMessageBox.warning(self, "Invalid PIN", "PIN must be exactly 4 digits.")
            return
        if p1 != p2:
            QMessageBox.warning(self, "Mismatch", "PINs do not match.")
            self.pin2.clear(); self.pin2.setFocus()
            return
        user_model.set_pin('admin', p1)
        self.accept()


class LoginScreen(QWidget):
    """
    Full-screen login shown before MainWindow.
    Emits login_successful signal with the user dict.
    """
    def __init__(self, on_login):
        super().__init__()
        self._on_login = on_login
        self._users = []
        self._selected_user = None
        self._countdown_username = None
        self.setWindowTitle("BackOfficePro — Login")
        self.setMinimumSize(500, 400)
        self.setStyleSheet("""
            QWidget  { background: #1a2332; color: #e6edf3; }
            QLabel   { background: transparent; }
        """)
        self._build_ui()
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._load_users()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Centre card
        centre = QHBoxLayout()
        centre.addStretch()
        card = QWidget()
        card.setFixedWidth(380)
        card.setStyleSheet("""
            QWidget { background: #1e2a38; border-radius: 12px; }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(16)

        # Title
        title = QLabel("BackOfficePro")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #e6edf3; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        sub = QLabel("Select your name and enter your PIN")
        sub.setStyleSheet("font-size: 12px; color: #8b949e; background: transparent;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a3a4a; background: transparent;")
        card_layout.addWidget(sep)

        # User buttons
        self._user_btn_area = QVBoxLayout()
        self._user_btn_area.setSpacing(8)
        card_layout.addLayout(self._user_btn_area)

        # PIN entry
        self.pin_label = QLabel("PIN")
        self.pin_label.setStyleSheet("color: #8b949e; font-size: 11px; background: transparent;")
        card_layout.addWidget(self.pin_label)

        self.pin_input = QLineEdit()
        self.pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_input.setMaxLength(4)
        self.pin_input.setPlaceholderText("••••")
        self.pin_input.setFixedHeight(48)
        self.pin_input.setStyleSheet("""
            QLineEdit {
                background: #1a2332; color: #e6edf3;
                border: 2px solid #2a3a4a; border-radius: 6px;
                padding: 8px; font-size: 22px; letter-spacing: 8px;
            }
            QLineEdit:focus { border-color: #1565c0; }
        """)
        self.pin_input.returnPressed.connect(self._attempt_login)
        card_layout.addWidget(self.pin_input)

        # Status label
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #f85149; font-size: 11px; background: transparent;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.status_lbl)

        # Login button
        self.login_btn = QPushButton("Login")
        self.login_btn.setFixedHeight(42)
        self.login_btn.setStyleSheet("""
            QPushButton { background: #1565c0; color: white; border: none;
                          border-radius: 6px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #1976d2; }
            QPushButton:disabled { background: #2a3a4a; color: #6e7681; }
        """)
        self.login_btn.clicked.connect(self._attempt_login)
        card_layout.addWidget(self.login_btn)

        centre.addWidget(card)
        centre.addStretch()

        root.addStretch()
        root.addLayout(centre)
        root.addStretch()

    def _load_users(self):
        for i in reversed(range(self._user_btn_area.count())):
            w = self._user_btn_area.itemAt(i).widget()
            if w:
                w.deleteLater()

        self._users = user_model.get_all_active()
        self._selected_user = None

        for user in self._users:
            name = user['full_name'] or user['username']
            btn = QPushButton(name)
            btn.setFixedHeight(38)
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton {
                    background: #1a2332; color: #e6edf3;
                    border: 1px solid #2a3a4a; border-radius: 6px;
                    font-size: 13px; text-align: left; padding: 0 12px;
                }
                QPushButton:checked {
                    background: #1565c0; border-color: #1976d2;
                }
                QPushButton:hover { background: #2a3a4a; }
            """)
            btn.clicked.connect(lambda _, u=user, b=btn: self._select_user(u, b))
            self._user_btn_area.addWidget(btn)

        if len(self._users) == 1:
            first_btn = self._user_btn_area.itemAt(0).widget()
            self._select_user(self._users[0], first_btn)

    def _select_user(self, user, btn):
        self._selected_user = user
        for i in range(self._user_btn_area.count()):
            w = self._user_btn_area.itemAt(i).widget()
            if w and w != btn:
                w.setChecked(False)
        btn.setChecked(True)
        self.pin_input.clear()

        # Stop any countdown running for the previous user
        self._countdown_timer.stop()
        self._countdown_username = None

        username = user['username']
        until = _lockout_until.get(username)
        if until and datetime.now() < until:
            self._start_countdown(username)
        else:
            self.status_lbl.clear()
            self.login_btn.setEnabled(True)
            self.pin_input.setEnabled(True)
            self.pin_input.setFocus()

    def _attempt_login(self):
        if not self._selected_user:
            self.status_lbl.setText("Please select your name first.")
            return

        username = self._selected_user['username']

        until = _lockout_until.get(username)
        if until and datetime.now() < until:
            # Guard against Enter key or button click while locked
            self._start_countdown(username)
            return

        pin = self.pin_input.text().strip()
        if not pin:
            self.status_lbl.setText("Please enter your PIN.")
            return

        if user_model.verify_pin(username, pin):
            _failed_attempts.pop(username, None)
            _lockout_until.pop(username, None)
            self._on_login(self._selected_user)
        else:
            attempts = _failed_attempts.get(username, 0) + 1
            _failed_attempts[username] = attempts
            self.pin_input.clear()

            if attempts >= _MAX_ATTEMPTS:
                _failed_attempts[username] = 0
                _lockout_until[username] = datetime.now() + timedelta(seconds=_LOCKOUT_SECONDS)
                self._start_countdown(username)
            else:
                remaining = _MAX_ATTEMPTS - attempts
                self.status_lbl.setText(f"Incorrect PIN. {remaining} attempt(s) remaining.")

    def _start_countdown(self, username):
        self._countdown_username = username
        self.login_btn.setEnabled(False)
        self.pin_input.setEnabled(False)
        if not self._countdown_timer.isActive():
            self._countdown_timer.start()
        self._tick_countdown()

    def _tick_countdown(self):
        username = self._countdown_username
        if not username:
            return
        until = _lockout_until.get(username)
        if not until:
            self._unlock()
            return
        remaining = max(0, int((until - datetime.now()).total_seconds()))
        if remaining <= 0:
            self._unlock()
        else:
            self.status_lbl.setText(f"Too many attempts. Try again in {remaining}s.")

    def _unlock(self):
        self._countdown_timer.stop()
        self._countdown_username = None
        self.login_btn.setEnabled(True)
        self.pin_input.setEnabled(True)
        self.pin_input.setFocus()
        self.status_lbl.setText("")
