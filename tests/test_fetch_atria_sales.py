"""Tests for scripts/fetch_atria_sales.py — the ATRIA catch-up sync."""
import datetime
from unittest.mock import MagicMock

import pytest

import scripts.fetch_atria_sales as atria


@pytest.fixture(autouse=True)
def _no_real_logging_or_disk(tmp_path, monkeypatch):
    """Never touch the real home directory or reconfigure root logging."""
    monkeypatch.setattr(atria, "OUTPUT_DIR", tmp_path / "ATRIA_Reports")
    monkeypatch.setattr(atria, "LOG_DIR", tmp_path / "ATRIA_Reports" / "logs")
    monkeypatch.setattr(atria, "setup_logging", lambda: None)


def _log_rows(db_conn):
    return db_conn.execute(
        "SELECT sale_date, row_count, status, error_message, unmatched_count "
        "FROM atria_import_log ORDER BY sale_date"
    ).fetchall()


# ── migrate_v60 ────────────────────────────────────────────────────────────────

class TestMigrateV60:
    def test_table_created_by_migration(self, tmp_path, monkeypatch):
        import sqlite3
        import database.connection as conn_mod
        import database.migrations as mig

        db_path = str(tmp_path / "v60.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.execute("CREATE TABLE db_meta (version INTEGER NOT NULL DEFAULT 1)")
        c.execute("INSERT INTO db_meta (version) VALUES (59)")
        c.close()
        conn_mod.invalidate_all_connections()

        mig.migrate_v60(conn_mod.get_connection())

        conn = conn_mod.get_connection()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(atria_import_log)").fetchall()}
        assert cols == {"sale_date", "imported_at", "row_count", "status", "error_message"}


# ── migrate_v61 ────────────────────────────────────────────────────────────────

class TestMigrateV61:
    def test_unmatched_count_column_added(self, tmp_path, monkeypatch):
        import sqlite3
        import database.connection as conn_mod
        import database.migrations as mig

        db_path = str(tmp_path / "v61.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.execute("CREATE TABLE db_meta (version INTEGER NOT NULL DEFAULT 1)")
        c.execute("INSERT INTO db_meta (version) VALUES (60)")
        c.execute("""
            CREATE TABLE atria_import_log (
                sale_date     TEXT PRIMARY KEY,
                imported_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                row_count     INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'OK',
                error_message TEXT
            )
        """)
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()

        mig.migrate_v61(conn_mod.get_connection())

        conn = conn_mod.get_connection()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(atria_import_log)").fetchall()}
        assert "unmatched_count" in cols

    def test_safe_to_run_twice(self, tmp_path, monkeypatch):
        """_add_column swallows 'duplicate column' — re-running must not raise."""
        import sqlite3
        import database.connection as conn_mod
        import database.migrations as mig

        db_path = str(tmp_path / "v61b.db")
        monkeypatch.setattr(conn_mod, "DATABASE_PATH", db_path)
        c = sqlite3.connect(db_path)
        c.execute("CREATE TABLE db_meta (version INTEGER NOT NULL DEFAULT 1)")
        c.execute("INSERT INTO db_meta (version) VALUES (60)")
        c.execute("""
            CREATE TABLE atria_import_log (
                sale_date TEXT PRIMARY KEY, row_count INTEGER, status TEXT, error_message TEXT
            )
        """)
        c.commit()
        c.close()
        conn_mod.invalidate_all_connections()

        conn = conn_mod.get_connection()
        mig.migrate_v61(conn)
        mig.migrate_v61(conn)  # must not raise


# ── _record_import_result ──────────────────────────────────────────────────────

class TestRecordImportResult:
    def test_insert_new_row(self, test_db, db_conn):
        atria._record_import_result("2026-07-01", 12, "OK")
        rows = _log_rows(db_conn)
        assert len(rows) == 1
        assert rows[0]["sale_date"] == "2026-07-01"
        assert rows[0]["row_count"] == 12
        assert rows[0]["status"] == "OK"
        assert rows[0]["unmatched_count"] == 0

    def test_upsert_overwrites_existing_row(self, test_db, db_conn):
        atria._record_import_result("2026-07-01", 5, "OK")
        atria._record_import_result("2026-07-01", 9, "OK")
        rows = _log_rows(db_conn)
        assert len(rows) == 1
        assert rows[0]["row_count"] == 9

    def test_error_status_records_message(self, test_db, db_conn):
        atria._record_import_result("2026-07-01", 0, "ERROR", "login failed")
        rows = _log_rows(db_conn)
        assert rows[0]["status"] == "ERROR"
        assert rows[0]["error_message"] == "login failed"

    def test_unmatched_count_persisted(self, test_db, db_conn):
        atria._record_import_result("2026-07-01", 12, "OK", unmatched_count=4)
        rows = _log_rows(db_conn)
        assert rows[0]["unmatched_count"] == 4

    def test_upsert_updates_unmatched_count(self, test_db, db_conn):
        atria._record_import_result("2026-07-01", 12, "OK", unmatched_count=4)
        atria._record_import_result("2026-07-01", 12, "OK", unmatched_count=0)
        rows = _log_rows(db_conn)
        assert rows[0]["unmatched_count"] == 0


# ── _missing_dates ──────────────────────────────────────────────────────────────

class TestMissingDates:
    def test_all_missing_when_log_empty(self, test_db):
        missing = atria._missing_dates(7)
        assert len(missing) == 7
        assert missing == sorted(missing)

    def test_none_missing_when_all_logged(self, test_db):
        today = datetime.date.today()
        for i in range(1, 8):
            d = today - datetime.timedelta(days=i)
            atria._record_import_result(d.isoformat(), 0, "OK")
        assert atria._missing_dates(7) == []

    def test_partial_returns_only_unlogged_dates_oldest_first(self, test_db):
        today = datetime.date.today()
        three_ago = today - datetime.timedelta(days=3)
        atria._record_import_result(three_ago.isoformat(), 0, "OK")

        missing = atria._missing_dates(7)
        assert three_ago not in missing
        assert len(missing) == 6
        assert missing == sorted(missing)

    def test_closed_day_with_zero_rows_still_counts_as_done(self, test_db):
        """A logged zero-sale day (store closed) must not be retried."""
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        atria._record_import_result(yesterday.isoformat(), 0, "OK")
        assert yesterday not in atria._missing_dates(7)


# ── sync_missing_days ─────────────────────────────────────────────────────────

class TestSyncMissingDays:
    def test_no_missing_days_skips_network_entirely(self, test_db, monkeypatch):
        today = datetime.date.today()
        for i in range(1, 8):
            d = today - datetime.timedelta(days=i)
            atria._record_import_result(d.isoformat(), 0, "OK")

        fake_login = MagicMock()
        monkeypatch.setattr(atria, "get_atria_credentials", MagicMock(return_value=("u", "p")))
        monkeypatch.setattr(atria, "login", fake_login)

        result = atria.sync_missing_days(days=7)

        assert result == {"imported": [], "failed": [], "skipped_reason": None, "unmatched_total": 0}
        fake_login.assert_not_called()

    def test_missing_credentials_skips_whole_run(self, test_db, monkeypatch):
        monkeypatch.setattr(
            atria, "get_atria_credentials",
            MagicMock(side_effect=RuntimeError("ATRIA credentials not set")),
        )
        result = atria.sync_missing_days(days=1)
        assert result["imported"] == []
        assert result["failed"] == []
        assert "credentials not set" in result["skipped_reason"]

    def test_login_failure_skips_whole_run(self, test_db, monkeypatch):
        monkeypatch.setattr(atria, "get_atria_credentials", MagicMock(return_value=("u", "p")))
        monkeypatch.setattr(atria, "login", MagicMock(side_effect=RuntimeError("bad login")))
        fake_fetch = MagicMock()
        monkeypatch.setattr(atria, "_fetch_and_import_one_day", fake_fetch)

        result = atria.sync_missing_days(days=1)

        assert result["skipped_reason"] == "bad login"
        fake_fetch.assert_not_called()

    def test_successful_multi_day_catchup(self, test_db, db_conn, monkeypatch):
        monkeypatch.setattr(atria, "get_atria_credentials", MagicMock(return_value=("u", "p")))
        monkeypatch.setattr(atria, "login", MagicMock())
        monkeypatch.setattr(atria, "_fetch_and_import_one_day", MagicMock(return_value=(3, 0)))

        result = atria.sync_missing_days(days=2)

        assert len(result["imported"]) == 2
        assert result["failed"] == []
        assert result["imported"] == sorted(result["imported"])
        rows = _log_rows(db_conn)
        assert len(rows) == 2
        assert all(r["status"] == "OK" and r["row_count"] == 3 for r in rows)

    def test_unmatched_plus_summed_across_run_and_logged(self, test_db, db_conn, monkeypatch):
        monkeypatch.setattr(atria, "get_atria_credentials", MagicMock(return_value=("u", "p")))
        monkeypatch.setattr(atria, "login", MagicMock())
        monkeypatch.setattr(atria, "_fetch_and_import_one_day", MagicMock(return_value=(3, 2)))

        result = atria.sync_missing_days(days=2)

        assert result["unmatched_total"] == 4
        rows = _log_rows(db_conn)
        assert all(r["unmatched_count"] == 2 for r in rows)

    def test_per_day_failure_recorded_and_loop_continues(self, test_db, db_conn, monkeypatch):
        monkeypatch.setattr(atria, "get_atria_credentials", MagicMock(return_value=("u", "p")))
        monkeypatch.setattr(atria, "login", MagicMock())

        missing = atria._missing_dates(2)  # oldest first

        def _fake_fetch(session, target_date):
            if target_date == missing[0]:
                raise RuntimeError("document never became ready")
            return 5, 0

        monkeypatch.setattr(atria, "_fetch_and_import_one_day", _fake_fetch)

        result = atria.sync_missing_days(days=2)

        assert result["failed"] == [missing[0].isoformat()]
        assert result["imported"] == [missing[1].isoformat()]
        rows = {r["sale_date"]: r for r in _log_rows(db_conn)}
        assert rows[missing[0].isoformat()]["status"] == "ERROR"
        assert "document never became ready" in rows[missing[0].isoformat()]["error_message"]
        assert rows[missing[1].isoformat()]["status"] == "OK"
        assert rows[missing[1].isoformat()]["row_count"] == 5


# ── _fetch_and_import_one_day ──────────────────────────────────────────────────

class TestFetchAndImportOneDay:
    def test_downloads_saves_and_imports(self, test_db, monkeypatch, tmp_path):
        target_date = datetime.date(2026, 7, 1)
        session = MagicMock()

        monkeypatch.setattr(atria, "create_client", MagicMock(return_value="client-1"))
        monkeypatch.setattr(atria, "create_instance", MagicMock(return_value="instance-1"))
        monkeypatch.setattr(atria, "request_csv_document", MagicMock(return_value="doc-1"))
        monkeypatch.setattr(atria, "download_document", MagicMock(return_value=b"plu,qty\n1,2\n"))

        fake_import_sales = MagicMock()
        fake_import_sales.import_csv.return_value = (7, 3, 1)
        monkeypatch.setattr(atria, "import_sales", fake_import_sales)

        atria.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        result = atria._fetch_and_import_one_day(session, target_date)

        assert result == (7, 1)
        fake_import_sales.ensure_tables.assert_called_once()
        saved_path = fake_import_sales.import_csv.call_args[0][0]
        assert saved_path.endswith("DailyPluSales_2026-07-01.csv")

        with open(saved_path, "rb") as f:
            assert f.read() == b"plu,qty\n1,2\n"

    def test_raises_when_download_fails(self, test_db, monkeypatch):
        session = MagicMock()
        monkeypatch.setattr(atria, "create_client", MagicMock(return_value="client-1"))
        monkeypatch.setattr(atria, "create_instance", MagicMock(return_value="instance-1"))
        monkeypatch.setattr(atria, "request_csv_document", MagicMock(return_value="doc-1"))
        monkeypatch.setattr(
            atria, "download_document",
            MagicMock(side_effect=RuntimeError("Gave up waiting for document")),
        )
        with pytest.raises(RuntimeError, match="Gave up waiting"):
            atria._fetch_and_import_one_day(session, datetime.date(2026, 7, 1))


# ── get_atria_credentials ──────────────────────────────────────────────────────

class TestGetAtriaCredentials:
    def test_reads_from_secret_store(self, monkeypatch):
        monkeypatch.setattr(atria, "get_secret", lambda key: {"atria_username": "bob", "atria_password": "pw"}[key])
        monkeypatch.delenv("ATRIA_USERNAME", raising=False)
        monkeypatch.delenv("ATRIA_PASSWORD", raising=False)
        assert atria.get_atria_credentials() == ("bob", "pw")

    def test_falls_back_to_env_vars(self, monkeypatch):
        monkeypatch.setattr(atria, "get_secret", lambda key: "")
        monkeypatch.setenv("ATRIA_USERNAME", "envuser")
        monkeypatch.setenv("ATRIA_PASSWORD", "envpass")
        assert atria.get_atria_credentials() == ("envuser", "envpass")

    def test_raises_clear_error_when_unset(self, monkeypatch):
        monkeypatch.setattr(atria, "get_secret", lambda key: "")
        monkeypatch.delenv("ATRIA_USERNAME", raising=False)
        monkeypatch.delenv("ATRIA_PASSWORD", raising=False)
        with pytest.raises(RuntimeError, match="--set-credentials"):
            atria.get_atria_credentials()


# ── extract_id ──────────────────────────────────────────────────────────────────

class TestExtractId:
    def test_returns_value_for_first_matching_key(self):
        assert atria.extract_id({"clientID": "abc123"}, ["clientID", "id"]) == "abc123"

    def test_tries_candidates_in_order(self):
        assert atria.extract_id({"id": "fallback"}, ["clientID", "id"]) == "fallback"

    def test_raises_key_error_with_raw_response_when_no_match(self):
        with pytest.raises(KeyError, match="unexpectedKey"):
            atria.extract_id({"unexpectedKey": "value"}, ["clientID", "id"])


# ── download_document retry logic ──────────────────────────────────────────────

class TestDownloadDocument:
    def test_returns_content_on_first_success(self, monkeypatch):
        monkeypatch.setattr(atria.time, "sleep", lambda s: None)
        session = MagicMock()
        resp = MagicMock(status_code=200, content=b"csv-bytes")
        session.get.return_value = resp
        result = atria.download_document(session, "c1", "i1", "d1")
        assert result == b"csv-bytes"
        assert session.get.call_count == 1

    def test_retries_until_ready_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(atria.time, "sleep", lambda s: None)
        session = MagicMock()
        not_ready = MagicMock(status_code=202, content=b"")
        ready = MagicMock(status_code=200, content=b"csv-bytes")
        session.get.side_effect = [not_ready, not_ready, ready]
        result = atria.download_document(session, "c1", "i1", "d1")
        assert result == b"csv-bytes"
        assert session.get.call_count == 3

    def test_gives_up_after_max_attempts(self, monkeypatch):
        monkeypatch.setattr(atria.time, "sleep", lambda s: None)
        monkeypatch.setattr(atria, "DOWNLOAD_RETRY_ATTEMPTS", 2)
        session = MagicMock()
        not_ready = MagicMock(status_code=202, content=b"")
        session.get.return_value = not_ready
        with pytest.raises(RuntimeError, match="Gave up waiting"):
            atria.download_document(session, "c1", "i1", "d1")
        assert session.get.call_count == 2
