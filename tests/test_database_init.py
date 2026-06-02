"""Tests for database/__init__.py init_db()."""
import pytest


def test_init_db_creates_tables(tmp_path, monkeypatch):
    import database.connection as conn_module
    monkeypatch.setattr(conn_module, "DATABASE_PATH", str(tmp_path / "test.db"))
    from database import init_db
    init_db()
    from database.connection import get_connection
    conn = get_connection()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.release()
    assert 'products' in tables
    assert 'departments' in tables
    assert 'suppliers' in tables


def test_init_db_idempotent(tmp_path, monkeypatch):
    import database.connection as conn_module
    monkeypatch.setattr(conn_module, "DATABASE_PATH", str(tmp_path / "test.db"))
    from database import init_db
    init_db()
    init_db()  # second call must not raise
