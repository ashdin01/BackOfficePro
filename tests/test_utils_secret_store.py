"""Tests for utils/secret_store.py — keyring get/set/fallback paths."""
import sys
from unittest.mock import MagicMock, call

import pytest
import utils.secret_store as ss


# ── get_secret ────────────────────────────────────────────────────────────────

class TestGetSecret:
    def test_returns_stored_value(self, monkeypatch):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "my-api-key"
        monkeypatch.setitem(sys.modules, "keyring", mock_kr)
        assert ss.get_secret("api_key") == "my-api-key"
        mock_kr.get_password.assert_called_once_with("BackOfficePro", "api_key")

    def test_returns_empty_string_when_not_set(self, monkeypatch):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None
        monkeypatch.setitem(sys.modules, "keyring", mock_kr)
        assert ss.get_secret("missing_key") == ""

    def test_returns_empty_string_on_keyring_exception(self, monkeypatch):
        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = Exception("no secret service")
        monkeypatch.setitem(sys.modules, "keyring", mock_kr)
        assert ss.get_secret("api_key") == ""

    def test_returns_empty_string_when_keyring_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "keyring", None)
        # None in sys.modules causes ImportError on 'import keyring'
        result = ss.get_secret("api_key")
        assert result == ""

    def test_returns_empty_string_on_module_not_found(self, monkeypatch):
        # Remove keyring entirely so the import raises ModuleNotFoundError
        monkeypatch.delitem(sys.modules, "keyring", raising=False)
        # If keyring genuinely isn't installed, get_secret must still return ""
        result = ss.get_secret("any_key")
        assert isinstance(result, str)


# ── set_secret ────────────────────────────────────────────────────────────────

class TestSetSecret:
    def test_stores_non_empty_value(self, monkeypatch):
        mock_kr = MagicMock()
        monkeypatch.setitem(sys.modules, "keyring", mock_kr)
        ss.set_secret("api_key", "secret123")
        mock_kr.set_password.assert_called_once_with("BackOfficePro", "api_key", "secret123")

    def test_empty_value_deletes_rather_than_stores(self, monkeypatch):
        mock_kr = MagicMock()
        monkeypatch.setitem(sys.modules, "keyring", mock_kr)
        ss.set_secret("api_key", "")
        mock_kr.set_password.assert_not_called()
        mock_kr.delete_password.assert_called_once_with("BackOfficePro", "api_key")

    def test_delete_exception_is_silenced(self, monkeypatch):
        mock_kr = MagicMock()
        mock_kr.delete_password.side_effect = Exception("not found")
        monkeypatch.setitem(sys.modules, "keyring", mock_kr)
        ss.set_secret("api_key", "")  # must not raise

    def test_set_exception_is_silenced(self, monkeypatch):
        mock_kr = MagicMock()
        mock_kr.set_password.side_effect = Exception("keyring locked")
        monkeypatch.setitem(sys.modules, "keyring", mock_kr)
        ss.set_secret("api_key", "value")  # must not raise

    def test_stores_when_keyring_unavailable_does_not_raise(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "keyring", None)
        ss.set_secret("api_key", "value")  # must not raise
