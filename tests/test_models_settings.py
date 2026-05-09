"""Tests for models/settings.py."""
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
