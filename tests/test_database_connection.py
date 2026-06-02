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
