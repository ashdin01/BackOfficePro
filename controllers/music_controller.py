"""Shop music — time-of-day slots, each mapped to a folder of audio files.

Pure logic (no PyQt6): the player widget asks which slot is active now and
which tracks it contains. Config is stored in the settings table:

    music_enabled      '1' / '0'
    music_volume       '0'-'100'
    music_output       audio output device id (hex of QAudioDevice.id()), '' = default
    music_slots        JSON list of {"name", "start" "HH:MM", "end" "HH:MM", "folder"}
"""
import json
import os
import random
from datetime import datetime, time

import controllers.settings_controller as settings_ctrl

AUDIO_EXTS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma')

DEFAULT_SLOTS = [
    {"name": "Morning",   "start": "08:00", "end": "11:00", "folder": ""},
    {"name": "Midday",    "start": "11:00", "end": "15:00", "folder": ""},
    {"name": "Afternoon", "start": "15:00", "end": "18:00", "folder": ""},
]


def _parse_hhmm(text) -> time:
    h, m = str(text).strip().split(':')
    return time(int(h), int(m))


def is_valid_hhmm(text) -> bool:
    try:
        _parse_hhmm(text)
        return True
    except (ValueError, TypeError):
        return False


def get_slots() -> list:
    raw = settings_ctrl.get_setting('music_slots', '')
    if not raw:
        return [dict(s) for s in DEFAULT_SLOTS]
    try:
        slots = json.loads(raw)
    except ValueError:
        return [dict(s) for s in DEFAULT_SLOTS]
    return [s for s in slots
            if isinstance(s, dict) and is_valid_hhmm(s.get('start')) and is_valid_hhmm(s.get('end'))]


def save_slots(slots: list) -> None:
    settings_ctrl.set_setting('music_slots', json.dumps(slots))


def is_enabled() -> bool:
    return settings_ctrl.get_setting('music_enabled', '0') == '1'


def set_enabled(on: bool) -> None:
    settings_ctrl.set_setting('music_enabled', '1' if on else '0')


def get_volume() -> int:
    try:
        return max(0, min(100, int(settings_ctrl.get_setting('music_volume', '50'))))
    except ValueError:
        return 50


def set_volume(vol: int) -> None:
    settings_ctrl.set_setting('music_volume', str(max(0, min(100, int(vol)))))


def get_output() -> str:
    return settings_ctrl.get_setting('music_output', '')


def set_output(device_id: str) -> None:
    settings_ctrl.set_setting('music_output', device_id)


def slot_for(now: datetime, slots: list = None):
    """Return the slot covering `now`, or None. Start inclusive, end exclusive;
    a slot whose end is <= its start runs past midnight."""
    if slots is None:
        slots = get_slots()
    t = now.time().replace(second=0, microsecond=0)
    for s in slots:
        start, end = _parse_hhmm(s['start']), _parse_hhmm(s['end'])
        if start < end:
            if start <= t < end:
                return s
        elif start > end:
            if t >= start or t < end:
                return s
    return None


def list_tracks(folder: str) -> list:
    """Audio files in `folder`, including subfolders, sorted by path."""
    if not folder or not os.path.isdir(folder):
        return []
    found = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(AUDIO_EXTS):
                found.append(os.path.join(root, f))
    return sorted(found)


def build_playlist(folder: str, rng=random) -> list:
    """Shuffled track list for a slot's folder."""
    tracks = list_tracks(folder)
    rng.shuffle(tracks)
    return tracks


def validate_slots(slots: list) -> str:
    """Return an error message, or '' if the slots are usable."""
    for s in slots:
        if not str(s.get('name', '')).strip():
            return "Every slot needs a name."
        if not (is_valid_hhmm(s.get('start')) and is_valid_hhmm(s.get('end'))):
            return f"Slot '{s.get('name')}': times must be HH:MM (24-hour)."
        if s['start'] == s['end']:
            return f"Slot '{s['name']}': start and end can't be the same."
    return ""
