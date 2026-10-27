"""Music settings — time-of-day slots, each mapped to a folder of audio files.

Music plays from the PC running BackOfficePro through the chosen Windows audio
output. Use music you are licensed to play in a shop (e.g. OneMusic, a
licensed business music service) — personal streaming accounts don't cover it.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton, QLabel, QCheckBox,
    QComboBox, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog,
)
from PyQt6.QtGui import QKeySequence, QShortcut
import controllers.music_controller as music_ctrl
from utils.error_dialog import show_error

_COLS = ["Slot name", "Start (HH:MM)", "End (HH:MM)", "Music folder"]


class MusicScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Music")
        self.setMinimumWidth(720)
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        note = QLabel(
            "Plays shuffled music from the folder assigned to the current time slot, "
            "switching automatically as the day moves on. Outside every slot, music stops. "
            "A slot ending earlier than it starts runs past midnight. "
            "Only play music your shop is licensed for."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: grey;")
        outer.addWidget(note)

        group = QGroupBox("Player")
        form = QFormLayout(group)
        self.enabled_chk = QCheckBox("Play music on this PC while BackOfficePro is open")
        form.addRow("", self.enabled_chk)
        self.device_cb = QComboBox()
        form.addRow("Audio output", self.device_cb)
        outer.addWidget(group)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table)

        btns = QHBoxLayout()
        add = QPushButton("Add slot")
        add.clicked.connect(lambda: self._add_row({"name": "", "start": "", "end": "", "folder": ""}))
        rem = QPushButton("Remove slot")
        rem.clicked.connect(self._remove_row)
        browse = QPushButton("Choose folder…")
        browse.clicked.connect(self._browse)
        for b in (add, rem, browse):
            btns.addWidget(b)
        btns.addStretch()
        outer.addLayout(btns)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel  [Esc]")
        cancel.clicked.connect(self.close)
        save = QPushButton("Save  [Ctrl+S]")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        outer.addLayout(row)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _add_row(self, slot):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, key in enumerate(("name", "start", "end", "folder")):
            self.table.setItem(r, c, QTableWidgetItem(slot.get(key, "")))

    def _remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def _browse(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Choose folder", "Select a slot row first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Music folder for this slot")
        if folder:
            self.table.setItem(r, 3, QTableWidgetItem(folder))

    def _load(self):
        from views.widgets.music_player import output_devices
        self.enabled_chk.setChecked(music_ctrl.is_enabled())
        self.device_cb.addItem("System default", "")
        for name, dev_id in output_devices():
            self.device_cb.addItem(name, dev_id)
        self.device_cb.setCurrentIndex(max(self.device_cb.findData(music_ctrl.get_output()), 0))
        for slot in music_ctrl.get_slots():
            self._add_row(slot)

    def _slots(self) -> list:
        def txt(r, c):
            it = self.table.item(r, c)
            return it.text().strip() if it else ""
        return [{"name": txt(r, 0), "start": txt(r, 1), "end": txt(r, 2), "folder": txt(r, 3)}
                for r in range(self.table.rowCount())]

    def _save(self):
        slots = self._slots()
        err = music_ctrl.validate_slots(slots)
        if err:
            QMessageBox.warning(self, "Music", err)
            return
        try:
            music_ctrl.save_slots(slots)
            music_ctrl.set_enabled(self.enabled_chk.isChecked())
            music_ctrl.set_output(self.device_cb.currentData() or "")
            from views.widgets.music_player import get_engine
            get_engine().reload()
        except Exception as e:
            show_error(self, "Could not save music settings.", e)
            return
        self.close()
