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

    def test_drift_raises_runtime_error(self, tmp_path, monkeypatch):
        """Tampering with a logged migration checksum must raise RuntimeError."""
        import sys
        # Only valid in non-frozen builds — the drift check is skipped when frozen.
        if getattr(sys, 'frozen', False):
            pytest.skip("drift check skipped in frozen build")

        db_path = self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()

        # Corrupt checksum for v2 (first real migration)
        c = sqlite3.connect(db_path)
        c.execute("UPDATE migration_log SET checksum='deadbeef' WHERE version=2")
        c.commit()
        c.close()

        # Invalidate connection cache so next get_connection() reopens
        conn_mod.invalidate_all_connections()

        with pytest.raises(RuntimeError, match="drift"):
            conn = conn_mod.get_connection()
            mig._check_integrity(conn)
            conn.release()

    def test_gap_warning_does_not_raise(self, tmp_path, monkeypatch, caplog):
        """A missing migration_log entry generates a WARNING but does not raise."""
        import logging
        db_path = self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        c.execute("DELETE FROM migration_log WHERE version=2")
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

    def test_skips_drift_check_when_frozen(self, tmp_path, monkeypatch):
        """A corrupted checksum would normally raise, but the drift check is
        skipped entirely for frozen (PyInstaller) builds."""
        import sys
        db_path = self._fresh_db(tmp_path, monkeypatch)
        mig.apply_migrations()

        c = sqlite3.connect(db_path)
        c.execute("UPDATE migration_log SET checksum='deadbeef' WHERE version=2")
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        conn = conn_mod.get_connection()
        mig._check_integrity(conn)  # must not raise despite corrupted checksum
        conn.release()

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

        # Start from the full current schema but pretend we're at v50.
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        # Walk db_meta back to 50 and remove log entries for v51+
        c.execute("UPDATE db_meta SET version=50")
        c.execute("CREATE TABLE IF NOT EXISTS migration_log "
                  "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, "
                  "description TEXT NOT NULL DEFAULT '', checksum TEXT NOT NULL DEFAULT '')")
        for v in mig._MIGRATIONS:
            if v <= 50:
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


# ── End-to-end migration chain ─────────────────────────────────────────────────

# Minimal schema representing the v1 state of the application.
# It contains ONLY tables and columns that existed before any migration ran.
# Columns added by migrations (even via _add_column) are deliberately absent
# so that every migration in the chain has something real to do.
#
# Key intentional omissions (added by later migrations):
#   products: brand(v3), sku/supplier_sku(v4), group_id(v6), pack_qty/pack_unit/
#             reorder_max/base_sku(v7), auto_reorder(v10), created_at/updated_at
#   suppliers: abn/rep_name/rep_phone/order_minimum(v5), email_orders/etc(v9),
#              address(v13), order_days(v23), bank_account_*(v32), …
#   purchase_orders: updated_at(v11), is_promo(v12 — on po_lines),
#                    po_type(v22), delivery_date/notes(missing at v1)
#   po_lines: actual_cost(v7), is_promo(v12), pack_qty(v21), is_note/sort_order(v31)
#   stock_movements: source(v33)
#   settings: schema_version seeded so early migrations can UPDATE it
#
# Tables NOT present at v1 (created by migrations):
#   barcode_aliases(v2), product_groups(v6), plu_barcode_map(v7), sales_daily(v7),
#   product_selling_units, bundles, bundle_eligible, customers, ar_invoices,
#   ar_invoice_lines, ar_payments, ar_credit_notes, bank_csv_profiles,
#   bank_transactions, po_charges, product_suppliers, stocktake_sessions,
#   stocktake_counts, audit_log, pos_sale_refs, migration_log, db_meta

_MINIMAL_SCHEMA_V1 = """
PRAGMA foreign_keys = ON;

CREATE TABLE departments (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    code   TEXT    NOT NULL UNIQUE,
    name   TEXT    NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
INSERT INTO departments (code, name) VALUES
    ('GROC', 'Grocery'), ('FRESH', 'Fresh'), ('DAIRY', 'Dairy'),
    ('MEAT', 'Meat'), ('LIQ', 'Liquor'), ('GM', 'General Merchandise'),
    ('BAKERY', 'Bakery'), ('FROZEN', 'Frozen'), ('DELI', 'Deli'),
    ('SEAFOOD', 'Seafood');

CREATE TABLE suppliers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    contact_name    TEXT,
    phone           TEXT,
    email           TEXT    DEFAULT '',
    account_number  TEXT,
    payment_terms   TEXT,
    notes           TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    barcode         TEXT PRIMARY KEY,
    plu             TEXT,
    description     TEXT NOT NULL,
    department_id   INTEGER NOT NULL REFERENCES departments(id),
    supplier_id     INTEGER REFERENCES suppliers(id),
    unit            TEXT    DEFAULT 'EA',
    sell_price      REAL    DEFAULT 0,
    cost_price      REAL    DEFAULT 0,
    tax_rate        REAL    DEFAULT 0,
    reorder_point   REAL    DEFAULT 0,
    reorder_qty     REAL    DEFAULT 0,
    variable_weight INTEGER NOT NULL DEFAULT 0,
    expected        INTEGER NOT NULL DEFAULT 1,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE purchase_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number     TEXT    NOT NULL UNIQUE,
    supplier_id   INTEGER NOT NULL REFERENCES suppliers(id),
    status        TEXT    NOT NULL DEFAULT 'DRAFT',
    delivery_date DATE,
    notes         TEXT,
    sent_at       DATETIME,
    received_at   DATETIME,
    created_by    TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE po_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id        INTEGER NOT NULL REFERENCES purchase_orders(id),
    barcode      TEXT    NOT NULL REFERENCES products(barcode),
    description  TEXT,
    ordered_qty  INTEGER DEFAULT 0,
    unit_cost    REAL    DEFAULT 0,
    received_qty INTEGER DEFAULT 0,
    notes        TEXT
);

CREATE TABLE stock_on_hand (
    barcode      TEXT PRIMARY KEY,
    quantity     REAL    DEFAULT 0,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE stock_movements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode       TEXT NOT NULL,
    movement_type TEXT NOT NULL,
    quantity      REAL    DEFAULT 0,
    reference     TEXT    DEFAULT '',
    notes         TEXT    DEFAULT '',
    created_by    TEXT    DEFAULT '',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE stocktake_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT    NOT NULL,
    department_id INTEGER,
    status        TEXT    NOT NULL DEFAULT 'OPEN',
    started_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at     DATETIME,
    created_by    TEXT,
    notes         TEXT,
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE stocktake_counts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES stocktake_sessions(id),
    barcode     TEXT    NOT NULL REFERENCES products(barcode),
    counted_qty REAL    NOT NULL DEFAULT 0,
    scanned_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    full_name     TEXT,
    pin           TEXT,
    password_hash TEXT,
    role          TEXT NOT NULL DEFAULT 'STAFF',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO users (username, full_name, role) VALUES ('admin', 'Administrator', 'ADMIN');

CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    description TEXT
);
INSERT INTO settings (key, value) VALUES
    ('po_prefix',       'PO'),
    ('po_next_number',  '1'),
    ('schema_version',  '1');
"""


class TestEndToEndMigrationChain:
    """Run apply_migrations() from a low version number to verify the full chain."""

    def _make_minimal_db(self, tmp_path, monkeypatch, name="chain.db"):
        """Create a DB from the minimal v1 schema with no db_meta table."""
        db_path = str(tmp_path / name)
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(_MINIMAL_SCHEMA_V1)
        c.close()
        conn_mod.invalidate_all_connections()
        return db_path

    def _make_db_at_version(self, tmp_path, monkeypatch, start_version, name=None):
        """Create a DB with the current SCHEMA but pretend it's at start_version.

        Only works for start_version >= the highest raw-ADD-COLUMN migration (v46),
        because the current SCHEMA already contains all those columns.
        """
        name = name or f"chain_v{start_version}.db"
        db_path = str(tmp_path / name)
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.execute("CREATE TABLE IF NOT EXISTS db_meta (version INTEGER NOT NULL DEFAULT 1)")
        c.execute("DELETE FROM db_meta")
        c.execute("INSERT INTO db_meta (version) VALUES (?)", (start_version,))
        c.execute("""
            CREATE TABLE IF NOT EXISTS migration_log (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                checksum TEXT NOT NULL DEFAULT ''
            )
        """)
        for v, (fn, desc) in mig._MIGRATIONS.items():
            if v <= start_version:
                c.execute(
                    "INSERT OR IGNORE INTO migration_log"
                    " (version, applied_at, description, checksum)"
                    " VALUES (?, 'pre-log', ?, ?)",
                    (v, desc, mig._fn_checksum(fn))
                )
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()
        return db_path

    def test_chain_from_v1_reaches_current(self, tmp_path, monkeypatch):
        """apply_migrations() from a true v1 minimal schema must reach current version."""
        db_path = self._make_minimal_db(tmp_path, monkeypatch, "chain_v1.db")
        mig.apply_migrations()
        c = sqlite3.connect(db_path)
        v = c.execute("SELECT version FROM db_meta").fetchone()[0]
        c.close()
        assert int(v) == max(mig._MIGRATIONS)

    def test_chain_from_v1_logs_all_migrations(self, tmp_path, monkeypatch):
        """Every migration must have a log entry after apply_migrations() from v1."""
        self._make_minimal_db(tmp_path, monkeypatch, "chain_v1_log.db")
        mig.apply_migrations()
        conn = conn_mod.get_connection()
        logged = {r[0] for r in conn.execute("SELECT version FROM migration_log").fetchall()}
        conn.release()
        for v in mig._MIGRATIONS:
            assert v in logged, f"migration_log missing entry for v{v} after full chain"

    def test_chain_v40_sequence_included(self, tmp_path, monkeypatch):
        """The v40 FK repair sequence (CHECK constraints + legacy_alter_table) must
        be part of the full chain run and the DB must reach the current version.

        v40 runs inside test_chain_from_v1_reaches_current, but this test
        specifically asserts that v40 is in the migration log after the chain.
        """
        db_path = self._make_minimal_db(tmp_path, monkeypatch, "chain_v40seq.db")
        mig.apply_migrations()
        c = sqlite3.connect(db_path)
        logged = {r[0] for r in c.execute("SELECT version FROM migration_log").fetchall()}
        v = int(c.execute("SELECT version FROM db_meta").fetchone()[0])
        c.close()
        assert 40 in logged, "v40 must be in migration_log"
        assert 42 in logged, "v42 (no-op after v40 legacy_alter_table fix) must be logged"
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
    """Verify drift detection catches a migration function whose source was changed."""

    def test_modified_function_raises_runtime_error(self, tmp_path, monkeypatch):
        """Replacing a live migration function raises RuntimeError on _check_integrity."""
        import sys
        if getattr(sys, 'frozen', False):
            pytest.skip("drift check skipped in frozen build")

        db_path = str(tmp_path / "fn_drift.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.executescript(SCHEMA)
        c.close()
        conn_mod.invalidate_all_connections()
        mig.apply_migrations()

        # Swap out migrate_v2 with a function that has different source code
        original_migrations = dict(mig._MIGRATIONS)

        def _altered_migrate_v2(conn):
            # This line makes the source different from the stored checksum
            conn.execute("SELECT 1")
            conn.commit()

        mig._MIGRATIONS[2] = (_altered_migrate_v2, original_migrations[2][1])

        try:
            conn_mod.invalidate_all_connections()
            with pytest.raises(RuntimeError, match="drift"):
                conn = conn_mod.get_connection()
                mig._check_integrity(conn)
                conn.release()
        finally:
            mig._MIGRATIONS[2] = original_migrations[2]
