"""Tests for database/migrations.py — drift detection and migration chain."""
import sqlite3
import pytest
import database.connection as conn_mod
import database.migrations as mig
from database.schema import SCHEMA


# ── Drift detection ───────────────────────────────────────────────────────────

class TestCheckIntegrity:
    def _fresh_db(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "integrity.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()
        return db_path

    def test_no_drift_on_clean_db(self, tmp_path, monkeypatch):
        """apply_migrations() on a fresh schema must not raise."""
        self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()  # must not raise

    def test_drift_logs_warning_does_not_raise(self, tmp_path, monkeypatch, caplog):
        """Tampering with a logged migration checksum logs a WARNING but does
        not raise — frozen-stamped checksums can never match a source-based
        recompute for entirely legitimate reasons, so drift is a hint, not a
        reliable fatal signal (see _check_integrity docstring)."""
        import sys, logging
        # Only valid in non-frozen builds — the drift check is skipped when frozen.
        if getattr(sys, 'frozen', False):
            pytest.skip("drift check skipped in frozen build")

        db_path = self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()

        # Corrupt checksum for v55 (first migration still in the registry)
        c = sqlite3.connect(db_path)
        c.execute("UPDATE migration_log SET checksum='deadbeef' WHERE version=55")
        c.commit()
        c.close()

        # Invalidate connection cache so next get_connection() reopens
        conn_mod.invalidate_all_connections()

        with caplog.at_level(logging.WARNING):
            conn = conn_mod.get_connection()
            mig._check_integrity(conn)  # must not raise
            conn.release()

        assert any("drift" in r.message.lower() for r in caplog.records)

    def test_gap_warning_does_not_raise(self, tmp_path, monkeypatch, caplog):
        """A missing migration_log entry generates a WARNING but does not raise."""
        import logging
        db_path = self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        c.execute("DELETE FROM migration_log WHERE version=55")
        c.commit()
        c.close()

        conn_mod.invalidate_all_connections()

        with caplog.at_level(logging.WARNING):
            conn = conn_mod.get_connection()
            mig._check_integrity(conn)  # must not raise
            conn.release()

        assert any("gap" in r.message.lower() for r in caplog.records)

    def test_returns_when_db_meta_has_no_version_row(self, tmp_path, monkeypatch):
        self._fresh_db(tmp_path, monkeypatch)
        conn = conn_mod.get_connection()
        conn.execute("DELETE FROM db_meta")
        conn.commit()
        mig._check_integrity(conn)  # must not raise, just return early
        conn.release()

    def test_skips_drift_check_when_frozen(self, tmp_path, monkeypatch, caplog):
        """The drift check (and its warning) is skipped entirely for frozen
        (PyInstaller) builds — recomputing there would just re-exercise the
        same bytecode-fallback path that stamped the checksum moments earlier,
        adding no information."""
        import sys, logging
        db_path = self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        c.execute("UPDATE migration_log SET checksum='deadbeef' WHERE version=55")
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        with caplog.at_level(logging.WARNING):
            conn = conn_mod.get_connection()
            mig._check_integrity(conn)  # must not raise despite corrupted checksum
            conn.release()

        assert not any("drift" in r.message.lower() for r in caplog.records)

    def test_skips_logged_version_no_longer_in_registry(self, tmp_path, monkeypatch):
        """A migration_log entry for a version number removed from _MIGRATIONS
        (e.g. old history) is skipped rather than crashing the drift check."""
        db_path = self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        c.execute("""
            INSERT INTO migration_log (version, applied_at, description, checksum)
            VALUES (99999, datetime('now'), 'no longer registered', 'whatever')
        """)
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()

        conn = conn_mod.get_connection()
        mig._check_integrity(conn)  # must not raise
        conn.release()


# ── _add_column ──────────────────────────────────────────────────────────────

class TestAddColumn:
    def test_reraises_non_duplicate_column_error(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "addcol.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()
        conn = conn_mod.get_connection()
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            mig._add_column(conn, "ALTER TABLE nonexistent_table ADD COLUMN x TEXT")
        conn.release()


# ── _fn_checksum ─────────────────────────────────────────────────────────────

class TestFnChecksum:
    def test_falls_back_to_bytecode_when_source_unavailable(self):
        """A function with no retrievable source (e.g. exec()'d) must still
        produce a stable checksum via the marshalled-bytecode fallback."""
        ns = {}
        exec("def _dynamic_fn(conn): pass", ns)
        fn = ns["_dynamic_fn"]
        checksum = mig._fn_checksum(fn)
        assert isinstance(checksum, str)
        assert len(checksum) == 64  # sha256 hex digest length


# ── apply_migrations failure path ─────────────────────────────────────────────

class TestApplyMigrationsFailure:
    def test_logs_critical_and_reraises_on_failure(self, tmp_path, monkeypatch, caplog):
        import logging
        self._fresh_db_for_failure(tmp_path, monkeypatch)
        monkeypatch.setattr(
            mig, "_ensure_migration_log",
            lambda conn: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with caplog.at_level(logging.CRITICAL):
            with pytest.raises(RuntimeError, match="boom"):
                mig.apply_migrations()
        assert any("Migration failed" in r.message for r in caplog.records)

    def _fresh_db_for_failure(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "failure.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()
        return db_path


# ── Full migration chain ───────────────────────────────────────────────────────

class TestFullMigrationChain:
    def test_fresh_schema_is_already_at_current_version(self, tmp_path, monkeypatch):
        """A fresh schema install seeds db_meta at the current max — no migrations should run."""
        db_path = str(tmp_path / "fresh.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()

        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        v = c.execute("SELECT version FROM db_meta").fetchone()
        c.close()
        assert int(v[0]) == max(mig._MIGRATIONS)

    def test_migration_reruns_only_missing_versions(self, tmp_path, monkeypatch):
        """apply_migrations() must only run migrations above the stored schema_version."""
        db_path = str(tmp_path / "partial.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)

        # Start from the full current schema but pretend we're at v60.
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        # Walk db_meta back to 60 and leave log entries only for v60 and below
        c.execute("UPDATE db_meta SET version=60")
        c.execute("CREATE TABLE IF NOT EXISTS migration_log "
                  "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, "
                  "description TEXT NOT NULL DEFAULT '', checksum TEXT NOT NULL DEFAULT '')")
        for v in mig._MIGRATIONS:
            if v <= 60:
                fn, desc = mig._MIGRATIONS[v]
                c.execute(
                    "INSERT OR IGNORE INTO migration_log (version, applied_at, description, checksum) "
                    "VALUES (?, 'pre-log', ?, ?)",
                    (v, desc, mig._fn_checksum(fn))
                )
        c.commit()
        c.close()

        conn_mod.invalidate_all_connections()
        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        v = c.execute("SELECT version FROM db_meta").fetchone()
        c.close()
        assert int(v[0]) == max(mig._MIGRATIONS)

    def test_migration_log_populated_after_apply(self, tmp_path, monkeypatch):
        """migration_log must contain an entry for every migration after apply_migrations."""
        db_path = str(tmp_path / "log_check.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()

        conn_mod.invalidate_all_connections()
        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        logged = {r[0] for r in c.execute("SELECT version FROM migration_log").fetchall()}
        c.close()

        for v in mig._MIGRATIONS:
            assert v in logged, f"migration_log missing entry for v{v}"


# ── Minimum supported version ─────────────────────────────────────────────────

class TestMinSupportedVersion:
    """v2-v54 were removed; a database older than MIN_SUPPORTED_VERSION must be
    refused with a clear message rather than half-migrated."""

    def _db_at(self, tmp_path, monkeypatch, version):
        db_path = str(tmp_path / f"v{version}.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.execute("UPDATE db_meta SET version=?", (version,))
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()
        return db_path

    def test_min_supported_version_is_below_every_registered_migration(self):
        assert mig.MIN_SUPPORTED_VERSION < min(mig._MIGRATIONS)

    def test_database_older_than_minimum_is_refused(self, tmp_path, monkeypatch):
        db_path = self._db_at(tmp_path, monkeypatch, mig.MIN_SUPPORTED_VERSION - 1)
        with pytest.raises(RuntimeError, match="v2.23.0"):
            mig.apply_migrations()
        c = sqlite3.connect(db_path)
        v = int(c.execute("SELECT version FROM db_meta").fetchone()[0])
        c.close()
        assert v == mig.MIN_SUPPORTED_VERSION - 1   # nothing was changed

    def test_database_at_minimum_is_upgraded_to_current(self, tmp_path, monkeypatch):
        db_path = self._db_at(tmp_path, monkeypatch, mig.MIN_SUPPORTED_VERSION)
        mig.apply_migrations()
        c = sqlite3.connect(db_path)
        v = int(c.execute("SELECT version FROM db_meta").fetchone()[0])
        c.close()
        assert v == max(mig._MIGRATIONS)

    def test_idempotent_when_already_current(self, tmp_path, monkeypatch):
        """apply_migrations() on a fully-current DB must be a no-op and not raise."""
        db_path = str(tmp_path / "current.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()
        conn_mod.invalidate_all_connections()
        mig.apply_migrations()  # first run
        mig.apply_migrations()  # second run — must be idempotent


# ── _check_integrity with modified function source ─────────────────────────────

class TestCheckIntegrityFunctionDrift:
    """Verify drift detection catches a migration function whose source was
    changed — logging a warning, not raising (see _check_integrity docstring:
    a frozen-stamped checksum can never match a source-based recompute for
    entirely legitimate reasons, so this is a hint, not a reliable fatal
    signal)."""

    def test_modified_function_logs_warning_does_not_raise(self, tmp_path, monkeypatch, caplog):
        import sys, logging
        if getattr(sys, 'frozen', False):
            pytest.skip("drift check skipped in frozen build")

        db_path = str(tmp_path / "fn_drift.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()
        conn_mod.invalidate_all_connections()
        mig.apply_migrations()

        # Swap out migrate_v55 with a function that has different source code
        original_migrations = dict(mig._MIGRATIONS)

        def _altered_migrate_v55(conn):
            # This line makes the source different from the stored checksum
            conn.execute("SELECT 1")
            conn.commit()

        mig._MIGRATIONS[55] = (_altered_migrate_v55, original_migrations[55][1])

        try:
            conn_mod.invalidate_all_connections()
            with caplog.at_level(logging.WARNING):
                conn = conn_mod.get_connection()
                mig._check_integrity(conn)  # must not raise
                conn.release()
            assert any("drift" in r.message.lower() for r in caplog.records)
        finally:
            mig._MIGRATIONS[55] = original_migrations[55]


# ── v73: backfill product_suppliers ───────────────────────────────────────────

class TestMigrateV73:
    def _db(self, tmp_path):
        c = sqlite3.connect(str(tmp_path / "v73.db"))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        c.execute("INSERT INTO departments (code, name) VALUES ('D', 'Dept')")
        c.execute("INSERT INTO suppliers (code, name) VALUES ('S1', 'Sup1')")
        c.execute("INSERT INTO suppliers (code, name) VALUES ('S2', 'Sup2')")
        return c

    def _product(self, c, barcode, supplier_id, sku='', pack_qty=1, pack_unit='ea'):
        c.execute(
            "INSERT INTO products (barcode, description, department_id, supplier_id,"
            " supplier_sku, pack_qty, pack_unit) VALUES (?, ?, 1, ?, ?, ?, ?)",
            (barcode, barcode, supplier_id, sku, pack_qty, pack_unit))

    def test_links_unlinked_product_with_its_sku_and_pack(self, tmp_path):
        c = self._db(tmp_path)
        self._product(c, 'A', 1, sku='SKU-A', pack_qty=6, pack_unit='ea')
        mig.migrate_v73(c)
        row = c.execute("SELECT * FROM product_suppliers WHERE barcode='A'").fetchone()
        assert (row['supplier_id'], row['is_default']) == (1, 1)
        assert (row['supplier_sku'], row['pack_qty'], row['pack_unit']) == ('SKU-A', 6, 'ea')

    def test_leaves_already_linked_and_supplierless_products_alone(self, tmp_path):
        c = self._db(tmp_path)
        self._product(c, 'B', 1)
        c.execute("INSERT INTO product_suppliers (barcode, supplier_id, is_default)"
                  " VALUES ('B', 2, 0)")
        self._product(c, 'C', None)
        mig.migrate_v73(c)
        rows = c.execute("SELECT barcode, supplier_id FROM product_suppliers").fetchall()
        assert [(r['barcode'], r['supplier_id']) for r in rows] == [('B', 2)]

    def test_is_idempotent(self, tmp_path):
        c = self._db(tmp_path)
        self._product(c, 'D', 1)
        mig.migrate_v73(c)
        mig.migrate_v73(c)
        assert c.execute("SELECT COUNT(*) FROM product_suppliers").fetchone()[0] == 1
