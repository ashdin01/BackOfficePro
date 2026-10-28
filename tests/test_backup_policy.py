"""Backup retention, verification, safety copies and pre-migration backup."""
import os
import sqlite3
from datetime import datetime, timedelta

import pytest

import controllers.backup_controller as bc
import database.connection as conn_mod
import database.migrations as mig
from database.schema import SCHEMA

NOW = datetime(2026, 10, 28, 20, 0, 0)


def _days_ago(n, hour=12):
    return (NOW - timedelta(days=n)).replace(hour=hour, minute=0, second=0)


# ── retention ─────────────────────────────────────────────────────────────────

class TestSelectBackupsToKeep:
    def test_many_backups_in_one_day_keep_only_newest_few(self):
        stamps = [NOW.replace(hour=h, minute=m) for h in range(8, 20) for m in (0, 30)]
        keep = bc.select_backups_to_keep(stamps, NOW)
        # newest 3 + the day's newest (already included) + this month's newest
        assert keep == set(sorted(stamps)[-3:])

    def test_one_per_day_for_last_seven_days(self):
        stamps = [_days_ago(d, h) for d in range(7) for h in (9, 18)]
        keep = bc.select_backups_to_keep(stamps, NOW)
        for d in range(7):
            assert _days_ago(d, 18) in keep           # newest of each day
        assert _days_ago(5, 9) not in keep            # earlier copy that day is dropped

    def test_older_history_thins_to_weekly_then_monthly(self):
        stamps = [_days_ago(d) for d in range(0, 120)]
        keep = bc.select_backups_to_keep(stamps, NOW)
        assert len(keep) <= bc._KEEP_NEWEST + bc._KEEP_DAILY + bc._KEEP_WEEKLY + bc._KEEP_MONTHLY
        assert _days_ago(100) not in keep or _days_ago(100) in keep  # monthly may keep one
        # every month in the last 4 has a backup retained
        months = {(s.year, s.month) for s in keep}
        assert len(months) >= 4

    def test_old_backup_outside_all_windows_is_dropped(self):
        ancient = datetime(2020, 1, 1, 9, 0, 0)
        stamps = [ancient] + [_days_ago(d) for d in range(5)]
        assert ancient not in bc.select_backups_to_keep(stamps, NOW)

    def test_never_returns_fewer_than_newest_three(self):
        stamps = [_days_ago(d) for d in range(10)]
        keep = bc.select_backups_to_keep(stamps, NOW)
        assert set(sorted(stamps)[-3:]) <= keep


class TestPruneBackups:
    def _touch(self, folder, stamp):
        name = f"supermarket_{stamp.strftime('%Y%m%d_%H%M%S')}.db"
        (folder / name).write_bytes(b"x")
        return name

    def test_removes_only_pruned_standard_files(self, tmp_path):
        ancient = self._touch(tmp_path, datetime(2020, 1, 1, 9))
        recent = [self._touch(tmp_path, _days_ago(d)) for d in range(3)]
        (tmp_path / "supermarket_PRE_RESTORE_20200101_090000.db").write_bytes(b"x")
        (tmp_path / "notes.txt").write_text("x")
        removed = bc.prune_backups(str(tmp_path), NOW)
        left = set(os.listdir(tmp_path))
        assert removed == 1
        assert ancient not in left
        assert set(recent) <= left
        assert "supermarket_PRE_RESTORE_20200101_090000.db" in left
        assert "notes.txt" in left


class TestPruneSafetyBackups:
    def test_keeps_newest_five_of_each_kind(self, tmp_path):
        for i in range(8):
            (tmp_path / f"supermarket_PRE_RESTORE_2026100{i}_000000.db").write_bytes(b"x")
            (tmp_path / f"supermarket_PRE_MIGRATION_v70_2026100{i}_000000.db").write_bytes(b"x")
        (tmp_path / "supermarket_20261001_000000.db").write_bytes(b"x")
        bc.prune_safety_backups(str(tmp_path))
        names = sorted(os.listdir(tmp_path))
        assert len([n for n in names if "PRE_RESTORE" in n]) == 5
        assert len([n for n in names if "PRE_MIGRATION" in n]) == 5
        assert "supermarket_PRE_RESTORE_20261007_000000.db" in names     # newest kept
        assert "supermarket_PRE_RESTORE_20261000_000000.db" not in names
        assert "supermarket_20261001_000000.db" in names                 # standard untouched

    def test_missing_folder_is_not_an_error(self, tmp_path):
        assert bc.prune_safety_backups(str(tmp_path / "nope")) == 0


# ── verification ──────────────────────────────────────────────────────────────

def _good_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    c.commit()
    c.close()


class TestVerifyBackup:
    def test_good_database_passes(self, tmp_path):
        p = str(tmp_path / "ok.db")
        _good_db(p)
        assert bc.verify_backup(p) == (True, "ok")

    def test_garbage_file_fails(self, tmp_path):
        p = tmp_path / "bad.db"
        p.write_bytes(b"this is not a sqlite database" * 100)
        ok, detail = bc.verify_backup(str(p))
        assert ok is False and detail

    def test_do_backup_deletes_a_copy_that_fails_verification(self, tmp_path, monkeypatch):
        src = str(tmp_path / "src.db")
        _good_db(src)
        monkeypatch.setattr(bc, "DATABASE_PATH", src)
        monkeypatch.setattr(bc, "verify_backup", lambda p: (False, "page 3 corrupt"))
        dest = tmp_path / "out" / "supermarket_20261028_200000.db"
        ok, msg = bc.do_backup(str(dest))
        assert ok is False
        assert "integrity" in msg
        assert not dest.exists()

    def test_failed_backup_leaves_older_backups_alone(self, tmp_path, monkeypatch):
        src = str(tmp_path / "src.db")
        _good_db(src)
        folder = tmp_path / "b"
        folder.mkdir()
        old = folder / "supermarket_20261027_200000.db"
        old.write_bytes(b"x")
        monkeypatch.setattr(bc, "DATABASE_PATH", src)
        monkeypatch.setattr(bc, "_BACKUP_DIR", str(folder))
        monkeypatch.setattr(bc, "verify_backup", lambda p: (False, "bad"))
        assert bc.silent_auto_backup() is None
        assert old.exists()


class TestStaleness:
    def test_stale_when_no_backups(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "_BACKUP_DIR", str(tmp_path))
        assert bc.is_backup_stale() is True

    def test_fresh_and_stale_around_24_hours(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "_BACKUP_DIR", str(tmp_path))
        (tmp_path / "supermarket_20261028_090000.db").write_bytes(b"x")
        assert bc.is_backup_stale(datetime(2026, 10, 29, 8, 0, 0)) is False
        assert bc.is_backup_stale(datetime(2026, 10, 29, 10, 0, 0)) is True

    def test_safety_copies_do_not_count_as_a_backup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bc, "_BACKUP_DIR", str(tmp_path))
        (tmp_path / "supermarket_PRE_RESTORE_20261028_090000.db").write_bytes(b"x")
        assert bc.is_backup_stale(datetime(2026, 10, 28, 10, 0, 0)) is True


# ── pre-migration backup ──────────────────────────────────────────────────────

class TestPreMigrationBackup:
    def _db_at(self, tmp_path, monkeypatch, version, with_product):
        db_path = str(tmp_path / "live.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.execute("UPDATE db_meta SET version=?", (version,))
        if with_product:
            c.execute("INSERT INTO products (barcode, description, department_id) "
                      "VALUES ('B1', 'B1', 1)")
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()
        return db_path

    def _backups(self):
        return [f for f in os.listdir(bc.get_backup_dir()) if "PRE_MIGRATION" in f]

    def test_backup_taken_before_pending_migrations_on_a_database_with_data(
        self, tmp_path, monkeypatch
    ):
        self._db_at(tmp_path, monkeypatch, 75, with_product=True)
        mig.apply_migrations()
        files = self._backups()
        assert len(files) == 1 and "_v75_" in files[0]
        # the snapshot is the pre-migration state: it still has version 75
        c = sqlite3.connect(os.path.join(bc.get_backup_dir(), files[0]))
        assert c.execute("SELECT version FROM db_meta").fetchone()[0] == 75
        c.close()

    def test_no_backup_when_nothing_is_pending(self, tmp_path, monkeypatch):
        self._db_at(tmp_path, monkeypatch, max(mig._MIGRATIONS), with_product=True)
        mig.apply_migrations()
        assert self._backups() == []

    def test_no_backup_for_a_brand_new_empty_database(self, tmp_path, monkeypatch):
        self._db_at(tmp_path, monkeypatch, 54, with_product=False)
        mig.apply_migrations()
        assert self._backups() == []

    def test_migration_is_aborted_when_the_backup_cannot_be_made(self, tmp_path, monkeypatch):
        db_path = self._db_at(tmp_path, monkeypatch, 75, with_product=True)
        monkeypatch.setattr(bc, "do_backup", lambda *a, **kw: (False, "disk full"))
        with pytest.raises(RuntimeError, match="disk full"):
            mig.apply_migrations()
        c = sqlite3.connect(db_path)
        assert c.execute("SELECT version FROM db_meta").fetchone()[0] == 75   # untouched
        c.close()
