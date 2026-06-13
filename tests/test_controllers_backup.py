"""Tests for controllers/backup_controller.py."""
import os
import sqlite3
import pytest
import controllers.backup_controller as backup_ctrl


# ── get_backup_dir ────────────────────────────────────────────────────────────

def test_get_backup_dir_returns_string():
    assert isinstance(backup_ctrl.get_backup_dir(), str)


def test_get_backup_dir_is_in_home():
    assert os.path.expanduser("~") in backup_ctrl.get_backup_dir()


# ── do_backup ─────────────────────────────────────────────────────────────────

class TestDoBackup:
    def _make_src_db(self, tmp_path):
        """Create a minimal source SQLite DB to back up."""
        src = str(tmp_path / "source.db")
        conn = sqlite3.connect(src)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()
        conn.close()
        import database.connection as conn_module
        conn_module.DATABASE_PATH = src
        return src

    def test_do_backup_returns_true_on_success(self, tmp_path, monkeypatch):
        src = self._make_src_db(tmp_path)
        import database.connection as conn_module
        monkeypatch.setattr(conn_module, "DATABASE_PATH", src)
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", src)
        dest = str(tmp_path / "backups" / "backup.db")
        ok, msg = backup_ctrl.do_backup(dest)
        assert ok is True
        assert "backup.db" in msg

    def test_do_backup_creates_file(self, tmp_path, monkeypatch):
        src = self._make_src_db(tmp_path)
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", src)
        dest = str(tmp_path / "backups" / "backup.db")
        backup_ctrl.do_backup(dest)
        assert os.path.exists(dest)

    def test_do_backup_file_is_readable_sqlite(self, tmp_path, monkeypatch):
        src = self._make_src_db(tmp_path)
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", src)
        dest = str(tmp_path / "backups" / "backup.db")
        backup_ctrl.do_backup(dest)
        conn = sqlite3.connect(dest)
        val = conn.execute("SELECT x FROM t").fetchone()[0]
        conn.close()
        assert val == 42

    def test_do_backup_returns_false_on_bad_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", "/nonexistent/source.db")
        ok, msg = backup_ctrl.do_backup(str(tmp_path / "backup.db"))
        assert ok is False
        assert msg  # error message present


# ── validate_backup_file ──────────────────────────────────────────────────────

class TestValidateBackupFile:
    def _make_valid_db(self, path):
        conn = sqlite3.connect(path)
        for tbl in backup_ctrl._REQUIRED_TABLES:
            conn.execute(f"CREATE TABLE {tbl} (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE db_meta (version INTEGER NOT NULL DEFAULT 1)")
        conn.execute("INSERT INTO db_meta (version) VALUES (54)")
        conn.commit()
        conn.close()

    def test_valid_file_returns_true_empty_set(self, tmp_path):
        db = str(tmp_path / "valid.db")
        self._make_valid_db(db)
        ok, missing = backup_ctrl.validate_backup_file(db)
        assert ok is True
        assert missing == set()

    def test_missing_table_detected(self, tmp_path):
        db = str(tmp_path / "partial.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        ok, missing = backup_ctrl.validate_backup_file(db)
        assert ok is False
        assert "suppliers" in missing

    def test_nonexistent_file_reports_all_tables_missing(self, tmp_path):
        # sqlite3.connect creates an empty DB rather than raising, so all required
        # tables will be missing — we get (False, full set of required tables).
        ok, missing = backup_ctrl.validate_backup_file(str(tmp_path / "ghost.db"))
        assert ok is False
        assert backup_ctrl._REQUIRED_TABLES.issubset(missing)


# ── get_last_backup_time ──────────────────────────────────────────────────────

class TestGetLastBackupTime:
    def test_returns_none_when_dir_missing(self, monkeypatch):
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", "/nonexistent/path/xyz")
        assert backup_ctrl.get_last_backup_time() is None

    def test_returns_datetime_for_valid_backup_filename(self, tmp_path, monkeypatch):
        from datetime import datetime
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", str(tmp_path))
        fname = tmp_path / "supermarket_20260101_120000.db"
        fname.write_text("")
        result = backup_ctrl.get_last_backup_time()
        assert result == datetime(2026, 1, 1, 12, 0, 0)

    def test_returns_most_recent_when_multiple(self, tmp_path, monkeypatch):
        from datetime import datetime
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", str(tmp_path))
        (tmp_path / "supermarket_20260101_080000.db").write_text("")
        (tmp_path / "supermarket_20260102_093000.db").write_text("")
        result = backup_ctrl.get_last_backup_time()
        assert result == datetime(2026, 1, 2, 9, 30, 0)

    def test_ignores_pre_restore_filenames(self, tmp_path, monkeypatch):
        from datetime import datetime
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", str(tmp_path))
        (tmp_path / "supermarket_PRE_RESTORE_20260519_200355.db").write_text("")
        (tmp_path / "supermarket_20260101_080000.db").write_text("")
        result = backup_ctrl.get_last_backup_time()
        assert result == datetime(2026, 1, 1, 8, 0, 0)

    def test_returns_none_when_only_pre_restore_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", str(tmp_path))
        (tmp_path / "supermarket_PRE_RESTORE_20260519_200355.db").write_text("")
        assert backup_ctrl.get_last_backup_time() is None


# ── get_backup_email ──────────────────────────────────────────────────────────

def test_get_backup_email_returns_str(test_db):
    result = backup_ctrl.get_backup_email()
    assert isinstance(result, str)


def test_get_backup_email_returns_empty_when_not_set(test_db):
    assert backup_ctrl.get_backup_email() == ""


# ── silent_auto_backup ────────────────────────────────────────────────────────

class TestSilentAutoBackup:
    def _make_src_db(self, tmp_path):
        src = str(tmp_path / "source.db")
        conn = sqlite3.connect(src)
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        return src

    def test_returns_path_on_success(self, tmp_path, monkeypatch):
        src = self._make_src_db(tmp_path)
        backup_dir = str(tmp_path / "backups")
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", src)
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", backup_dir)
        result = backup_ctrl.silent_auto_backup()
        assert result is not None
        assert result.endswith(".db")

    def test_backup_file_actually_created(self, tmp_path, monkeypatch):
        src = self._make_src_db(tmp_path)
        backup_dir = str(tmp_path / "backups")
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", src)
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", backup_dir)
        result = backup_ctrl.silent_auto_backup()
        assert os.path.exists(result)

    def test_prunes_old_backups_beyond_keep_count(self, tmp_path, monkeypatch):
        src = self._make_src_db(tmp_path)
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir)
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", src)
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", backup_dir)
        monkeypatch.setattr(backup_ctrl, "_KEEP_COUNT", 2)
        # Pre-create 3 old backup files
        for i in range(3):
            (tmp_path / "backups" / f"supermarket_2025010{i}_000000.db").write_text("")
        backup_ctrl.silent_auto_backup()
        remaining = [f for f in os.listdir(backup_dir) if f.endswith(".db")]
        assert len(remaining) <= 2

    def test_returns_none_on_bad_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", "/nonexistent/source.db")
        monkeypatch.setattr(backup_ctrl, "_BACKUP_DIR", str(tmp_path / "backups"))
        result = backup_ctrl.silent_auto_backup()
        assert result is None


# ── restore_backup ────────────────────────────────────────────────────────────

class TestRestoreBackup:
    def _make_full_db(self, path):
        conn = sqlite3.connect(path)
        for tbl in backup_ctrl._REQUIRED_TABLES:
            conn.execute(f"CREATE TABLE {tbl} (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

    def _patch_migrations(self, monkeypatch):
        import database.migrations as mig
        monkeypatch.setattr(mig, "apply_migrations", lambda: None)

    def test_restore_raises_on_missing_tables(self, tmp_path, monkeypatch):
        self._patch_migrations(monkeypatch)
        src = str(tmp_path / "bad_src.db")
        conn = sqlite3.connect(src)
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        dest = str(tmp_path / "dest.db")
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", dest)
        with pytest.raises(RuntimeError, match="missing tables"):
            backup_ctrl.restore_backup(src)

    def test_restore_succeeds_with_valid_source(self, tmp_path, monkeypatch):
        self._patch_migrations(monkeypatch)
        src = str(tmp_path / "valid_src.db")
        self._make_full_db(src)
        dest = str(tmp_path / "dest.db")
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", dest)
        backup_ctrl.restore_backup(src)
        assert os.path.exists(dest)
        conn = sqlite3.connect(dest)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert backup_ctrl._REQUIRED_TABLES.issubset(tables)

    def test_restore_runs_migrations_after_copy(self, tmp_path, monkeypatch):
        import database.migrations as mig
        calls = []
        monkeypatch.setattr(mig, "apply_migrations", lambda: calls.append(1))
        src = str(tmp_path / "valid_src.db")
        self._make_full_db(src)
        dest = str(tmp_path / "dest.db")
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", dest)
        backup_ctrl.restore_backup(src)
        assert calls, "apply_migrations() was not called after restore"


# ── migrate_v37 product_selling_units guard ───────────────────────────────────

class TestMigrateV37SellingUnitsGuard:
    """Regression: migrate_v37 must not crash when product_selling_units is absent.

    Databases created before the table was added to schema.py hit
    'no such table: product_selling_units' on restore because migrate_v37
    assumed the table already existed and tried to RENAME it immediately.
    """

    def test_migrate_v37_creates_selling_units_when_absent(self, tmp_path, monkeypatch):
        """migrate_v37 must not crash when product_selling_units is absent.

        Uses the current full schema, drops product_selling_units to simulate
        the pre-introduction state, then runs migrate_v37 directly and asserts
        the table is recreated correctly.
        """
        import database.connection as conn_mod
        from database.schema import SCHEMA
        from database.migrations import migrate_v37

        db_path = str(tmp_path / "no_selling_units.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)

        # Fresh DB with full current schema
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        # Drop the table to simulate the missing-table condition
        c.execute("DROP TABLE IF EXISTS product_selling_units")
        c.execute("DROP INDEX IF EXISTS idx_selling_units_master")
        c.execute("DROP INDEX IF EXISTS idx_selling_units_barcode")
        c.commit()
        c.close()

        # Confirm the table is absent
        c = sqlite3.connect(db_path)
        tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        c.close()
        assert 'product_selling_units' not in tables

        # Run migrate_v37 directly — must not raise
        conn = conn_mod.get_connection()
        try:
            migrate_v37(conn)
        finally:
            conn.release()

        # Table must exist after the migration
        c = sqlite3.connect(db_path)
        tables_after = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        c.close()
        assert 'product_selling_units' in tables_after


# ── backup_to_local_path ──────────────────────────────────────────────────────

class TestBackupToLocalPath:
    """Extra backup destination (USB / external drive)."""

    def _set_path(self, value):
        import models.settings as settings_model
        settings_model.set_setting('backup_local_path', value)

    def test_unconfigured_path_fails_cleanly(self, test_db):
        self._set_path('')
        ok, msg = backup_ctrl.backup_to_local_path()
        assert ok is False
        assert "No backup folder configured" in msg

    def test_missing_folder_fails_with_drive_hint(self, test_db):
        self._set_path('/nonexistent/usb/mount')
        ok, msg = backup_ctrl.backup_to_local_path()
        assert ok is False
        assert "plugged in" in msg

    def test_writes_timestamped_backup_into_folder(self, test_db, tmp_path, monkeypatch):
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", test_db)
        folder = tmp_path / "usb"
        folder.mkdir()
        self._set_path(str(folder))
        ok, _ = backup_ctrl.backup_to_local_path()
        assert ok is True
        files = list(folder.glob("supermarket_*.db"))
        assert len(files) == 1
        # Backup must be a readable BackOfficePro database
        c = sqlite3.connect(files[0])
        tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        c.close()
        assert "products" in tables

    def test_prune_keeps_recent_and_ignores_unrelated_files(self, test_db, tmp_path, monkeypatch):
        monkeypatch.setattr(backup_ctrl, "DATABASE_PATH", test_db)
        folder = tmp_path / "usb"
        folder.mkdir()
        self._set_path(str(folder))
        # Seed more than _KEEP_COUNT old backups plus unrelated files
        for i in range(backup_ctrl._KEEP_COUNT + 5):
            (folder / f"supermarket_202001{i:02d}_000000.db").write_bytes(b"old")
        (folder / "holiday_photos.db").write_bytes(b"keep me")
        (folder / "notes.txt").write_text("keep me too")

        ok, _ = backup_ctrl.backup_to_local_path()
        assert ok is True
        ours = list(folder.glob("supermarket_*.db"))
        assert len(ours) == backup_ctrl._KEEP_COUNT
        # Unrelated files untouched even though one ends in .db
        assert (folder / "holiday_photos.db").exists()
        assert (folder / "notes.txt").exists()

    def test_get_backup_local_path_strips_whitespace(self, test_db):
        self._set_path('  /media/usb  ')
        assert backup_ctrl.get_backup_local_path() == '/media/usb'
