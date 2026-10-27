"""Tests for music_controller (slot resolution, track listing, settings)."""
import random
from datetime import datetime

import controllers.music_controller as music

SLOTS = [
    {"name": "Morning", "start": "08:00", "end": "11:00", "folder": "a"},
    {"name": "Late",    "start": "22:00", "end": "02:00", "folder": "b"},
]


def at(h, m=0):
    return datetime(2026, 10, 25, h, m)


class TestSlotFor:
    def test_inside_slot(self):
        assert music.slot_for(at(9, 30), SLOTS)["name"] == "Morning"

    def test_start_inclusive_end_exclusive(self):
        assert music.slot_for(at(8, 0), SLOTS)["name"] == "Morning"
        assert music.slot_for(at(11, 0), SLOTS) is None

    def test_gap_returns_none(self):
        assert music.slot_for(at(15), SLOTS) is None

    def test_wraps_past_midnight(self):
        assert music.slot_for(at(23), SLOTS)["name"] == "Late"
        assert music.slot_for(at(1, 59), SLOTS)["name"] == "Late"
        assert music.slot_for(at(2), SLOTS) is None


class TestTracks:
    def test_lists_audio_recursively_and_ignores_others(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"")
        (tmp_path / "notes.txt").write_bytes(b"")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.FLAC").write_bytes(b"")
        names = [p.rsplit("/", 1)[-1] for p in music.list_tracks(str(tmp_path))]
        assert names == ["a.mp3", "b.FLAC"]

    def test_missing_folder_is_empty(self):
        assert music.list_tracks("/no/such/dir") == []
        assert music.list_tracks("") == []

    def test_playlist_is_shuffled_permutation(self, tmp_path):
        for i in range(10):
            (tmp_path / f"{i}.mp3").write_bytes(b"")
        pl = music.build_playlist(str(tmp_path), rng=random.Random(1))
        assert sorted(pl) == music.list_tracks(str(tmp_path))


class TestSettings:
    def test_defaults(self, test_db):
        assert music.is_enabled() is False
        assert music.get_volume() == 50
        assert len(music.get_slots()) == 3

    def test_slots_roundtrip(self, test_db):
        music.save_slots(SLOTS)
        assert music.get_slots() == SLOTS

    def test_corrupt_slots_fall_back(self, test_db):
        import controllers.settings_controller as s
        s.set_setting('music_slots', '{not json')
        assert len(music.get_slots()) == 3

    def test_volume_clamped(self, test_db):
        music.set_volume(250)
        assert music.get_volume() == 100

    def test_validate(self):
        assert music.validate_slots(SLOTS) == ""
        assert "HH:MM" in music.validate_slots([{"name": "x", "start": "8am", "end": "10:00"}])
        assert music.validate_slots([{"name": "", "start": "08:00", "end": "10:00"}])
        assert music.validate_slots([{"name": "x", "start": "08:00", "end": "08:00"}])
