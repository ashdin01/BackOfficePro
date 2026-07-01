"""Backup settings screen — automatic email backup and local/USB backup folder."""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QSizePolicy, QScrollArea,
)
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt
import config.styles as styles
import controllers.settings_controller as settings_ctrl
from utils.validators import validate_email
from utils.error_dialog import show_error

BACKUP_FIELDS = [
    ("backup_email", "Email backup to", "e.g. owner@yourbusiness.com.au — leave blank to disable"),
]


class BackupScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Backup")
        self.setMinimumWidth(580)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._fields: dict[str, QLineEdit] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("Backup")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(16)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(scroll_widget)
        outer.addWidget(scroll, stretch=1)

        # ── Backup ────────────────────────────────────────────────────
        backup_group = QGroupBox("Backup")
        backup_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        backup_form = QFormLayout(backup_group)
        backup_form.setContentsMargins(16, 16, 16, 16)
        backup_form.setSpacing(10)
        backup_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for key, label, placeholder in BACKUP_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumWidth(360)
            backup_form.addRow(label, edit)
            self._fields[key] = edit
        backup_note = QLabel(
            "💡 Uses the Microsoft 365 email configuration from Settings → Purchase Orders.\n"
            "    The database backup is attached and sent automatically on app close."
        )
        backup_note.setStyleSheet("color: grey; font-size: 8pt;")
        backup_note.setWordWrap(True)
        backup_form.addRow("", backup_note)

        # Extra backup destination — USB / external drive
        folder_row = QHBoxLayout()
        folder_edit = QLineEdit()
        folder_edit.setPlaceholderText("e.g. /media/usb or E:\\Backups — leave blank to disable")
        folder_row.addWidget(folder_edit, stretch=1)
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_backup_folder)
        folder_row.addWidget(btn_browse)
        backup_form.addRow("Also back up to", folder_row)
        self._fields["backup_local_path"] = folder_edit

        folder_note = QLabel(
            "💡 Extra copy written to this folder (e.g. a USB drive) on every app close.\n"
            "    Keeps the most recent 30 — other files in the folder are never touched."
        )
        folder_note.setStyleSheet("color: grey; font-size: 8pt;")
        folder_note.setWordWrap(True)
        backup_form.addRow("", folder_note)

        btn_backup_now = QPushButton("Backup Now to Folder")
        btn_backup_now.setFixedHeight(30)
        btn_backup_now.clicked.connect(self._backup_to_folder_now)
        backup_form.addRow("", btn_backup_now)

        btn_test_backup = QPushButton("Send Test Backup Email")
        btn_test_backup.setFixedHeight(30)
        btn_test_backup.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT_HOVER}; color: white; border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT}; }}"
        )
        btn_test_backup.clicked.connect(self._test_backup_email)
        backup_form.addRow("", btn_test_backup)
        scroll_layout.addWidget(backup_group)

        scroll_layout.addStretch()

        # ── Buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(self.close)

        btn_save = QPushButton("Save  [Ctrl+S]")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
            f"border-radius: 4px; padding: 0 18px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
        )
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_save)
        outer.addLayout(btn_row)

        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        settings = settings_ctrl.get_all_settings()
        for key, edit in self._fields.items():
            edit.setText(settings.get(key, ""))

    def _save(self):
        try:
            backup_email_val = validate_email(self._fields["backup_email"].text())
        except ValueError as e:
            QMessageBox.warning(self, "Validation", f"Backup Email: {e}")
            return

        for key, edit in self._fields.items():
            if key == "backup_email":
                settings_ctrl.set_setting(key, backup_email_val)
            else:
                settings_ctrl.set_setting(key, edit.text().strip())

        QMessageBox.information(self, "Saved", "Backup settings saved successfully.")
        self.close()

    def _browse_backup_folder(self):
        from PyQt6.QtWidgets import QFileDialog
        start = self._fields["backup_local_path"].text().strip() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choose Backup Folder", start)
        if folder:
            self._fields["backup_local_path"].setText(folder)

    def _backup_to_folder_now(self):
        path = self._fields["backup_local_path"].text().strip()
        settings_ctrl.set_setting("backup_local_path", path)
        if not path:
            QMessageBox.warning(self, "No Folder Selected",
                                "Choose a backup folder first (e.g. your USB drive).")
            return
        try:
            import controllers.backup_controller as backup_ctrl
            ok, msg = backup_ctrl.backup_to_local_path()
            if ok:
                QMessageBox.information(self, "Backup Complete", msg)
            else:
                QMessageBox.critical(self, "Backup Failed", msg)
        except Exception as e:
            show_error(self, "Could not back up to folder.", e)

    def _test_backup_email(self):
        settings_ctrl.set_setting("backup_email", self._fields["backup_email"].text().strip())
        to_address = self._fields["backup_email"].text().strip()
        if not to_address:
            QMessageBox.warning(self, "No Email Address",
                                "Enter an email address in the 'Email backup to' field first.")
            return
        try:
            import controllers.backup_controller as backup_ctrl
            from utils.email_graph import send_backup
            dest = backup_ctrl.silent_auto_backup()
            if not dest:
                QMessageBox.critical(self, "Backup Failed",
                                     "Could not create a backup file to send.")
                return
            send_backup(dest, to_address)
            QMessageBox.information(self, "Test Backup Email Sent",
                                    f"Backup emailed successfully to:\n{to_address}")
        except ImportError as e:
            QMessageBox.critical(self, "Missing Library",
                                 f"Email library not available: {e}\n\nRun: pip install msal")
        except RuntimeError as e:
            QMessageBox.critical(self, "Email Configuration Error", str(e))
        except Exception as e:
            show_error(self, "Could not send test backup email.", e)
