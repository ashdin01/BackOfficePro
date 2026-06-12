"""Tests for utils/api_key.py — shared API key resolution.

The critical property: the Settings screen and the API server must resolve
the SAME key whether or not the OS keyring works. The keyring-works cases
mirror Windows (Credential Manager); the keyring-broken cases mirror a Linux
box without a Secret Service backend.
"""
import pytest

import models.settings as settings_model
import utils.api_key as ak


class FakeKeyring:
    """In-memory stand-in for utils.secret_store backed by a dict.

    working=False simulates a machine with no usable keyring backend:
    get always returns '' and set silently does nothing — matching
    secret_store's swallow-and-warn behaviour.
    """

    def __init__(self, working=True):
        self.working = working
        self.store = {}

    def get(self, key):
        return self.store.get(key, "") if self.working else ""

    def set(self, key, value):
        if not self.working:
            return False
        if value:
            self.store[key] = value
        else:
            self.store.pop(key, None)
        return True


@pytest.fixture()
def keyring_ok(monkeypatch):
    fake = FakeKeyring(working=True)
    monkeypatch.setattr(ak, "get_secret", fake.get)
    monkeypatch.setattr(ak, "set_secret", fake.set)
    return fake


@pytest.fixture()
def keyring_broken(monkeypatch):
    fake = FakeKeyring(working=False)
    monkeypatch.setattr(ak, "get_secret", fake.get)
    monkeypatch.setattr(ak, "set_secret", fake.set)
    return fake


# ── resolve_api_key ───────────────────────────────────────────────────────────

class TestResolveApiKey:
    def test_returns_keyring_key_when_present(self, test_db, keyring_ok):
        keyring_ok.store["api_key"] = "kr-key"
        settings_model.set_setting("api_key", "stale-db-key")
        assert ak.resolve_api_key() == "kr-key"
        # DB copy untouched — only the migration path clears it
        assert settings_model.get_setting("api_key") == "stale-db-key"

    def test_migrates_db_key_to_keyring_and_clears_db(self, test_db, keyring_ok):
        settings_model.set_setting("api_key", "legacy-db-key")
        assert ak.resolve_api_key() == "legacy-db-key"
        assert keyring_ok.store["api_key"] == "legacy-db-key"
        assert settings_model.get_setting("api_key") == ""

    def test_keyring_broken_keeps_db_key(self, test_db, keyring_broken):
        settings_model.set_setting("api_key", "db-key")
        assert ak.resolve_api_key() == "db-key"
        assert settings_model.get_setting("api_key") == "db-key"

    def test_generates_into_keyring_when_neither_has_key(self, test_db, keyring_ok):
        settings_model.set_setting("api_key", "")
        key = ak.resolve_api_key()
        assert len(key) == 64  # token_hex(32)
        assert keyring_ok.store["api_key"] == key
        assert settings_model.get_setting("api_key") == ""

    def test_generates_into_db_when_keyring_broken(self, test_db, keyring_broken):
        settings_model.set_setting("api_key", "")
        key = ak.resolve_api_key()
        assert len(key) == 64
        assert settings_model.get_setting("api_key") == key

    def test_stable_across_repeat_calls_keyring_ok(self, test_db, keyring_ok):
        # Regression: server resolved via keyring while the Settings screen
        # read only the DB, so on Windows they showed different keys.
        settings_model.set_setting("api_key", "legacy-db-key")
        first  = ak.resolve_api_key()   # server at startup (migrates)
        second = ak.resolve_api_key()   # settings screen later
        assert first == second == "legacy-db-key"

    def test_stable_across_repeat_calls_keyring_broken(self, test_db, keyring_broken):
        settings_model.set_setting("api_key", "")
        first  = ak.resolve_api_key()   # generates
        second = ak.resolve_api_key()
        assert first == second


# ── store_api_key ─────────────────────────────────────────────────────────────

class TestStoreApiKey:
    def test_stores_in_keyring_and_clears_db(self, test_db, keyring_ok):
        settings_model.set_setting("api_key", "old-db-key")
        ak.store_api_key("new-key")
        assert keyring_ok.store["api_key"] == "new-key"
        assert settings_model.get_setting("api_key") == ""
        assert ak.resolve_api_key() == "new-key"

    def test_falls_back_to_db_when_keyring_broken(self, test_db, keyring_broken):
        ak.store_api_key("new-key")
        assert settings_model.get_setting("api_key") == "new-key"
        assert ak.resolve_api_key() == "new-key"
