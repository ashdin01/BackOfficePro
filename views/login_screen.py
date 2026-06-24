from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QDialog, QFormLayout, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from datetime import datetime, timedelta
import controllers.user_controller as user_ctrl
import config.styles as styles
import config.settings as _cfg_settings

_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 30

# Module-level counters survive login screen close/reopen within the same app
# session, preventing bypass by dismissing and reopening the widget.
# Limitation: counters reset on application restart. A determined attacker
# with physical access can brute-force PINs by restarting the app. This is
# accepted for a local desktop application — the primary threat model assumes
# the machine itself is in a controlled environment. If stricter lockout is
# required, persist counters to the settings table.
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
        self.setStyleSheet(
            f"QDialog{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};}}"
            f"QLabel{{color:{styles.CLR_TEXT};background:transparent;}}"
            f"QLineEdit{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};"
            f"border:1px solid {styles.CLR_BORDER};border-radius:4px;"
            "padding:6px;font-size:18px;letter-spacing:4px;}"
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:8px 20px;font-weight:bold;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Welcome to BackOfficePro")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        info = QLabel("No PIN has been set yet.\nCreate a 4-digit PIN for the Admin account to continue.")
        info.setStyleSheet(styles.STYLE_LABEL_MUTED)
        info.setWordWrap(True)
        layout.addWidget(info)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(styles.STYLE_SEPARATOR)
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
        user_ctrl.set_pin('admin', p1)
        self.accept()


class LoginScreen(QWidget):
    """
    Full-screen login shown before MainWindow.
    Emits login_successful signal with the user dict.
    """
    def __init__(self, on_login, merged=False):
        super().__init__()
        self._on_login = on_login
        self._merged = merged
        self._users = []
        self._selected_user = None
        self._countdown_username = None
        if merged:
            self.setWindowTitle("BackOfficePro — Login")
        else:
            _store = _cfg_settings.ACTIVE_STORE_NAME
            self.setWindowTitle(f"BackOfficePro — {_store} — Login" if _store else "BackOfficePro — Login")
        self.setMinimumSize(500, 400)
        self.setStyleSheet(
            f"QWidget{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};}}"
            "QLabel{background:transparent;}"
        )
        self._build_ui()
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        if not self._merged:
            self._load_users()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Centre card
        centre = QHBoxLayout()
        centre.addStretch()
        card = QWidget()
        card.setFixedWidth(380)
        card.setStyleSheet(
            f"QWidget{{background:{styles.CLR_BG_PANEL};border-radius:12px;}}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(16)

        # Title
        title = QLabel("BackOfficePro")
        title.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {styles.CLR_TEXT}; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        sub_text = "Enter your username and PIN" if self._merged else "Select your name and enter your PIN"
        sub = QLabel(sub_text)
        sub.setStyleSheet(f"font-size: 12px; color: {styles.CLR_MUTED}; background: transparent;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"{styles.STYLE_SEPARATOR} background: transparent;")
        card_layout.addWidget(sep)

        if self._merged:
            # Username entry — no store/user list shown. The correct store
            # is resolved from the username itself at login time.
            self.username_label = QLabel("Username")
            self.username_label.setStyleSheet(f"{styles.STYLE_LABEL_MUTED} background: transparent;")
            card_layout.addWidget(self.username_label)

            self.username_input = QLineEdit()
            self.username_input.setPlaceholderText("e.g. jsmith")
            self.username_input.setFixedHeight(40)
            self.username_input.setStyleSheet(
                f"QLineEdit{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};"
                f"border:2px solid {styles.CLR_BORDER};border-radius:6px;"
                "padding:8px;font-size:14px;}"
                f"QLineEdit:focus{{border-color:{styles.CLR_ACCENT};}}"
            )
            self.username_input.returnPressed.connect(lambda: self.pin_input.setFocus())
            card_layout.addWidget(self.username_input)
        else:
            # User buttons
            self._user_btn_area = QVBoxLayout()
            self._user_btn_area.setSpacing(8)
            card_layout.addLayout(self._user_btn_area)

        # PIN entry
        self.pin_label = QLabel("PIN")
        self.pin_label.setStyleSheet(f"{styles.STYLE_LABEL_MUTED} background: transparent;")
        card_layout.addWidget(self.pin_label)

        self.pin_input = QLineEdit()
        self.pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_input.setMaxLength(4)
        self.pin_input.setPlaceholderText("••••")
        self.pin_input.setFixedHeight(48)
        self.pin_input.setStyleSheet(
            f"QLineEdit{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};"
            f"border:2px solid {styles.CLR_BORDER};border-radius:6px;"
            "padding:8px;font-size:22px;letter-spacing:8px;}"
            f"QLineEdit:focus{{border-color:{styles.CLR_ACCENT};}}"
        )
        self.pin_input.returnPressed.connect(self._attempt_login)
        card_layout.addWidget(self.pin_input)

        # Status label
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {styles.CLR_DANGER}; font-size: 11px; background: transparent;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.status_lbl)

        # Login button
        self.login_btn = QPushButton("Login")
        self.login_btn.setFixedHeight(42)
        self.login_btn.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:6px;font-size:14px;font-weight:bold;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
            f"QPushButton:disabled{{background:{styles.CLR_BORDER};color:{styles.CLR_EXTRA_DIM};}}"
        )
        self.login_btn.clicked.connect(self._attempt_login)
        card_layout.addWidget(self.login_btn)

        centre.addWidget(card)
        centre.addStretch()

        root.addStretch()
        root.addLayout(centre)
        root.addStretch()

        if self._merged:
            self.username_input.setFocus()

    def _load_users(self):
        for i in reversed(range(self._user_btn_area.count())):
            w = self._user_btn_area.itemAt(i).widget()
            if w:
                w.deleteLater()

        self._users = user_ctrl.list_all_active_users() if self._merged else user_ctrl.get_all_active()
        self._selected_user = None

        for user in self._users:
            name = user['full_name'] or user['username']
            if self._merged and user.get('store_name'):
                name = f"{name} ({user['store_name']})"
            btn = QPushButton(name)
            btn.setFixedHeight(38)
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"QPushButton{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};"
                f"border:1px solid {styles.CLR_BORDER};border-radius:6px;"
                "font-size:13px;text-align:left;padding:0 12px;}"
                f"QPushButton:checked{{background:{styles.CLR_ACCENT};border-color:{styles.CLR_ACCENT_HOVER};}}"
                f"QPushButton:hover{{background:{styles.CLR_BORDER};}}"
            )
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
        if self._merged:
            self._attempt_login_merged()
        else:
            self._attempt_login_single()

    def _attempt_login_single(self):
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

        if user_ctrl.verify_pin(username, pin):
            _failed_attempts.pop(username, None)
            _lockout_until.pop(username, None)
            self._on_login(self._selected_user)
        else:
            self._record_failed_attempt(username, "Incorrect PIN.")

    def _attempt_login_merged(self):
        username = self.username_input.text().strip().lower()
        pin = self.pin_input.text().strip()

        if not username or not pin:
            self.status_lbl.setText("Enter your username and PIN.")
            return

        until = _lockout_until.get(username)
        if until and datetime.now() < until:
            # Guard against Enter key or button click while locked
            self._start_countdown(username)
            return

        # Look up the username before knowing whether it exists at all — the
        # error message stays the same either way, so a typo can't be used
        # to fish for valid usernames.
        user = user_ctrl.find_user_for_login(username)
        if user is None:
            self._record_failed_attempt(username, "Invalid username or PIN.")
            return

        self._switch_to_store(user)

        if user_ctrl.verify_pin(username, pin):
            _failed_attempts.pop(username, None)
            _lockout_until.pop(username, None)
            self._on_login(user)
        else:
            self._record_failed_attempt(username, "Invalid username or PIN.")

    def _record_failed_attempt(self, username: str, message: str):
        attempts = _failed_attempts.get(username, 0) + 1
        _failed_attempts[username] = attempts
        self.pin_input.clear()

        if attempts >= _MAX_ATTEMPTS:
            _failed_attempts[username] = 0
            _lockout_until[username] = datetime.now() + timedelta(seconds=_LOCKOUT_SECONDS)
            self._start_countdown(username)
        else:
            remaining = _MAX_ATTEMPTS - attempts
            self.status_lbl.setText(f"{message} {remaining} attempt(s) remaining.")

    def _switch_to_store(self, user):
        """Point the app's active database at this user's store before
        verifying their PIN (merged cross-store login only)."""
        db_path = user.get('db_path')
        store_name = user.get('store_name')
        if not db_path or not store_name:
            return
        import database.connection as _db_conn
        _cfg_settings.DATABASE_PATH = db_path
        _cfg_settings.ACTIVE_STORE_NAME = store_name
        _db_conn.DATABASE_PATH = db_path

    def _start_countdown(self, username):
        self._countdown_username = username
        self.login_btn.setEnabled(False)
        self.pin_input.setEnabled(False)
        if self._merged:
            self.username_input.setEnabled(False)
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
        if self._merged:
            self.username_input.setEnabled(True)
        self.pin_input.setFocus()
        self.status_lbl.setText("")
