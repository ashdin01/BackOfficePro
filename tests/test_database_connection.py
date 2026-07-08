"""Tests for database/connection.py — retry, proxy, and invalidation paths."""
import sqlite3
import pytest


def test_get_connection_returns_usable_connection(test_db):
    from database.connection import get_connection
    conn = get_connection()
    row = conn.execute("SELECT 1 AS val").fetchone()
    assert row['val'] == 1
    conn.release()


def test_connection_proxy_getattr_delegates_to_raw(test_db):
    from database.connection import get_connection
    conn = get_connection()
    # .commit is an attribute on the raw sqlite3.Connection — proxy must delegate
    assert callable(conn.commit)
    conn.release()


def test_executemany_works(test_db):
    from database.connection import get_connection
    conn = get_connection()
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [("__test_k1", "v1"), ("__test_k2", "v2")],
    )
    conn.commit()
    rows = conn.execute(
        "SELECT value FROM settings WHERE key IN ('__test_k1','__test_k2')"
    ).fetchall()
    assert len(rows) == 2
    conn.release()


def test_close_is_alias_for_release(test_db):
    from database.connection import get_connection
    conn = get_connection()
    conn.execute("BEGIN")
    conn.close()  # must not raise and must not close the underlying connection


def test_invalidate_all_connections_forces_reconnect(test_db):
    from database.connection import get_connection, invalidate_all_connections
    conn1 = get_connection()
    id1 = id(conn1)
    invalidate_all_connections()
    conn2 = get_connection()
    # After invalidation the proxy object is replaced
    assert id(conn2) != id1
    conn2.release()


def test_close_thread_connection_does_not_raise(test_db):
    from database.connection import get_connection, close_thread_connection
    get_connection()
    close_thread_connection()  # must not raise
    close_thread_connection()  # second call (conn already None) must not raise


def test_retry_on_lock_retries_then_raises(test_db, monkeypatch):
    """_retry_on_lock should retry on 'database is locked' and eventually raise."""
    import database.connection as conn_mod
    calls = []

    original = conn_mod._retry_on_lock

    def fake_retry(fn, *args):
        # Simulate lock by raising on every call
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(conn_mod, "_retry_on_lock", fake_retry)
    conn = conn_mod.get_connection()
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        conn.execute("SELECT 1")
    conn_mod._retry_on_lock = original


def test_rollback_failure_logged(test_db, monkeypatch, caplog):
    """If rollback raises, the error is logged but does not propagate."""
    import logging
    from database.connection import get_connection, _Connection
    import database.connection as conn_mod

    # Build a _Connection wrapping a mock whose rollback raises
    from unittest.mock import MagicMock
    mock_raw = MagicMock()
    mock_raw.rollback.side_effect = Exception("rollback exploded")
    bad_conn = _Connection(mock_raw)

    with caplog.at_level(logging.WARNING, logger='root'):
        bad_conn.release()  # must not raise despite rollback failure
    assert any("rollback" in r.message.lower() for r in caplog.records)


def test_connection_proxy_setattr_delegates_to_raw(test_db):
    """Setting an attribute on the proxy must set it on the wrapped raw connection."""
    from database.connection import get_connection
    conn = get_connection()
    conn.text_factory = bytes
    raw = object.__getattribute__(conn, '_raw')
    assert raw.text_factory is bytes
    conn.release()


def test_retry_on_lock_retries_then_succeeds(monkeypatch, caplog):
    """The real retry loop should sleep/retry on transient locks then return the result."""
    import logging
    import database.connection as conn_mod

    monkeypatch.setattr(conn_mod.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    with caplog.at_level(logging.WARNING, logger='root'):
        result = conn_mod._retry_on_lock(flaky)

    assert result == "ok"
    assert calls["n"] == 3
    assert sum("lock contention" in r.message.lower() for r in caplog.records) == 2


def test_retry_on_lock_reraises_non_lock_error_immediately(monkeypatch):
    """A non-'locked' OperationalError must propagate without retrying."""
    import database.connection as conn_mod
    calls = {"n": 0}

    def raise_other():
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table: foo")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        conn_mod._retry_on_lock(raise_other)
    assert calls["n"] == 1


def test_stale_connection_close_failure_logged_on_reconnect(test_db, tmp_path, caplog):
    """If closing a stale cached connection raises, it's logged and a fresh
    connection is still created (the DATABASE_PATH-changed reconnect path)."""
    import logging
    import database.connection as conn_mod
    from unittest.mock import MagicMock

    conn_mod.get_connection().release()  # populate this thread's cache
    cached = conn_mod._local.conn
    mock_raw = MagicMock()
    mock_raw.close.side_effect = Exception("boom")
    object.__setattr__(cached, '_raw', mock_raw)
    # Force a path mismatch so get_connection() treats the cached conn as stale.
    conn_mod._local.path = str(tmp_path / "different.db")

    with caplog.at_level(logging.WARNING, logger='root'):
        new_conn = conn_mod.get_connection()
    new_conn.execute("SELECT 1").fetchone()
    new_conn.release()

    assert any("closing stale connection" in r.message.lower() for r in caplog.records)


def test_close_thread_connection_failure_logged(test_db, caplog):
    """If closing the thread connection raises, it's logged and the cache is
    still cleared."""
    import logging
    import database.connection as conn_mod
    from unittest.mock import MagicMock

    conn_mod.get_connection()
    cached = conn_mod._local.conn
    mock_raw = MagicMock()
    mock_raw.close.side_effect = Exception("boom")
    object.__setattr__(cached, '_raw', mock_raw)

    with caplog.at_level(logging.WARNING, logger='root'):
        conn_mod.close_thread_connection()

    assert any("closing thread connection" in r.message.lower() for r in caplog.records)
    assert conn_mod._local.conn is None
