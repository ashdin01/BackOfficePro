"""Tests for models/settings.py."""
import threading
import pytest
import models.settings as settings_model


def test_get_existing_setting(test_db):
    s = settings_model.get_setting('store_name')
    assert isinstance(s, str)


def test_get_missing_setting_returns_default(test_db):
    assert settings_model.get_setting('nonexistent_key') == ''
    assert settings_model.get_setting('nonexistent_key', 'fallback') == 'fallback'


def test_set_new_setting(test_db):
    settings_model.set_setting('test_key', 'hello')
    assert settings_model.get_setting('test_key') == 'hello'


def test_set_overwrites_existing(test_db):
    settings_model.set_setting('test_key2', 'first')
    settings_model.set_setting('test_key2', 'second')
    assert settings_model.get_setting('test_key2') == 'second'


def test_set_and_get_empty_string(test_db):
    settings_model.set_setting('empty_key', '')
    # empty string stored as empty — default not used when key exists
    from database.connection import get_connection
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key='empty_key'").fetchone()
    conn.close()
    assert row is not None


def test_next_sequence_increments(test_db):
    a = settings_model.next_sequence('test_seq', 'TST')
    b = settings_model.next_sequence('test_seq', 'TST')
    assert a == 'TST-00001'
    assert b == 'TST-00002'


def test_next_sequence_concurrent_no_duplicates(test_db):
    """Concurrent callers must each get a unique sequence number."""
    results = []
    errors = []

    def worker():
        try:
            results.append(settings_model.next_sequence('inv_seq', 'INV'))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(results) == 20
    assert len(set(results)) == 20, f"Duplicate sequence numbers: {sorted(results)}"
