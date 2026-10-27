"""Shop music player — plays the playlist for the current time-of-day slot.

MusicEngine is a process-wide singleton (MainWindow._build_ui re-runs on every
lock/relogin, so the player must outlive the sidebar panel). MusicPanel is the
small sidebar control bound to it. Output goes to the chosen Windows audio
device (default device if none chosen) — route that device to the shop amp.
"""
import logging
import os
from datetime import datetime

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, Qt
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

import config.styles as styles
import controllers.music_controller as music_ctrl

_TICK_MS = 30_000


def output_devices():
    """[(display name, id string)] for every audio output the OS offers."""
    return [(d.description(), bytes(d.id()).hex()) for d in QMediaDevices.audioOutputs()]


class MusicEngine(QObject):
    changed = pyqtSignal()   # now-playing / state changed — panels refresh

    def __init__(self):
        super().__init__()
        self._audio = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)
        self._slot_key = None      # (name, folder) of the slot being played
        self._playlist = []
        self._idx = 0
        self._failures = 0
        self.user_paused = False
        self.slot_name = ""
        self.now_playing = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(_TICK_MS)
        self.reload()

    # ── config ────────────────────────────────────────────────────────
    def reload(self):
        """Re-read settings (volume, device, slots) and apply immediately."""
        self._audio.setVolume(music_ctrl.get_volume() / 100)
        want = music_ctrl.get_output()
        if want:
            for d in QMediaDevices.audioOutputs():
                if bytes(d.id()).hex() == want:
                    self._audio.setDevice(d)
                    break
        else:
            self._audio.setDevice(QMediaDevices.defaultAudioOutput())
        self.tick()

    def set_volume(self, vol: int):
        music_ctrl.set_volume(vol)
        self._audio.setVolume(vol / 100)

    # ── scheduling ────────────────────────────────────────────────────
    def tick(self):
        if not music_ctrl.is_enabled():
            self._stop("")
            return
        slot = music_ctrl.slot_for(datetime.now())
        if slot is None:
            self._stop("")
            return
        key = (slot['name'], slot.get('folder', ''))
        if key != self._slot_key:
            self._slot_key = key
            self.slot_name = slot['name']
            self._playlist = music_ctrl.build_playlist(slot.get('folder', ''))
            self._idx = 0
            self._failures = 0
            if not self._playlist:
                logging.warning("[music] slot %r has no tracks in %r", key[0], key[1])
                self._player.stop()
                self.now_playing = ""
                self.changed.emit()
                return
            if not self.user_paused:
                self._play_current()
        self.changed.emit()

    def _stop(self, why):
        self._player.stop()
        self._slot_key = None
        self._playlist = []
        self.slot_name = why
        self.now_playing = ""
        self.changed.emit()

    # ── playback ──────────────────────────────────────────────────────
    def _play_current(self):
        if not self._playlist:
            return
        path = self._playlist[self._idx]
        self.now_playing = os.path.splitext(os.path.basename(path))[0]
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        self.changed.emit()

    def next(self):
        if not self._playlist:
            return
        self._idx += 1
        if self._idx >= len(self._playlist):
            self._playlist = music_ctrl.build_playlist(self._slot_key[1])
            self._idx = 0
            if not self._playlist:
                return
        self._play_current()

    def toggle_pause(self):
        if not music_ctrl.is_enabled() or not self._playlist:
            return
        if self.user_paused:
            self.user_paused = False
            if self._player.source().isEmpty():
                self._play_current()
            else:
                self._player.play()
        else:
            self.user_paused = True
            self._player.pause()
        self.changed.emit()

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._failures = 0
            self.next()

    def _on_error(self, _err, msg):
        logging.warning("[music] playback error on %r: %s", self.now_playing, msg)
        self._failures += 1
        if self._failures >= max(len(self._playlist), 1):
            self._stop("")      # every track failed — stop rather than spin
            return
        self.next()

    @property
    def is_playing(self):
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState


_engine = None


def get_engine() -> MusicEngine:
    global _engine
    if _engine is None:
        _engine = MusicEngine()
    return _engine


class MusicPanel(QWidget):
    """Compact sidebar control: slot, track, pause/next, volume."""

    def __init__(self):
        super().__init__()
        self._engine = get_engine()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.slot_lbl = QLabel("")
        self.slot_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.slot_lbl.setStyleSheet(f"color: {styles.CLR_MUTED}; font-size: 9px;")
        lay.addWidget(self.slot_lbl)

        self.track_lbl = QLabel("")
        self.track_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_lbl.setWordWrap(True)
        self.track_lbl.setStyleSheet(f"color: {styles.CLR_TEXT}; font-size: 10px;")
        lay.addWidget(self.track_lbl)

        row = QHBoxLayout()
        self.pause_btn = QPushButton("⏸")
        self.next_btn = QPushButton("⏭")
        for b in (self.pause_btn, self.next_btn):
            b.setFixedHeight(28)
        self.pause_btn.clicked.connect(self._engine.toggle_pause)
        self.next_btn.clicked.connect(self._engine.next)
        row.addWidget(self.pause_btn)
        row.addWidget(self.next_btn)
        lay.addLayout(row)

        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(music_ctrl.get_volume())
        self.vol.setToolTip("Music volume")
        self.vol.valueChanged.connect(self._engine.set_volume)
        lay.addWidget(self.vol)

        self._engine.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        on = music_ctrl.is_enabled()
        self.setVisible(on)
        if not on:
            return
        e = self._engine
        self.slot_lbl.setText(f"♪ {e.slot_name}" if e.slot_name else "♪ no slot now")
        self.track_lbl.setText(e.now_playing or "—")
        self.pause_btn.setText("▶" if e.user_paused or not e.is_playing else "⏸")
        v = music_ctrl.get_volume()
        if self.vol.value() != v:
            self.vol.blockSignals(True)
            self.vol.setValue(v)
            self.vol.blockSignals(False)
