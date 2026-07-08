"""Tests for utils/error_dialog.py — show_error() logging + dialog behavior."""
import logging
from unittest.mock import MagicMock

import utils.error_dialog as error_dialog


def _patch_qmessagebox(monkeypatch):
    mock_cls = MagicMock()
    monkeypatch.setattr(error_dialog, "QMessageBox", mock_cls)
    return mock_cls


class TestShowErrorWithException:
    def test_shows_context_and_exception_detail(self, monkeypatch):
        mock_mb = _patch_qmessagebox(monkeypatch)
        exc = ValueError("bad value")

        error_dialog.show_error(None, "Failed to save product", exc)

        mock_mb.critical.assert_called_once_with(
            None, "Error", "Failed to save product\n\nDetail: bad value"
        )

    def test_logs_with_exc_info(self, monkeypatch, caplog):
        _patch_qmessagebox(monkeypatch)
        exc = ValueError("bad value")

        with caplog.at_level(logging.ERROR):
            error_dialog.show_error(None, "Failed to save product", exc)

        assert "Failed to save product: bad value" in caplog.text
        assert any(r.exc_info is not None for r in caplog.records)

    def test_custom_title_passed_through(self, monkeypatch):
        mock_mb = _patch_qmessagebox(monkeypatch)
        error_dialog.show_error(None, "ctx", ValueError("x"), title="Custom Title")
        assert mock_mb.critical.call_args[0][1] == "Custom Title"

    def test_parent_widget_passed_through(self, monkeypatch):
        mock_mb = _patch_qmessagebox(monkeypatch)
        parent = object()
        error_dialog.show_error(parent, "ctx", ValueError("x"))
        assert mock_mb.critical.call_args[0][0] is parent


class TestShowErrorWithoutException:
    def test_shows_context_only(self, monkeypatch):
        mock_mb = _patch_qmessagebox(monkeypatch)
        error_dialog.show_error(None, "Something went wrong")
        mock_mb.critical.assert_called_once_with(None, "Error", "Something went wrong")

    def test_logs_without_exc_info(self, monkeypatch, caplog):
        _patch_qmessagebox(monkeypatch)
        with caplog.at_level(logging.ERROR):
            error_dialog.show_error(None, "Something went wrong")

        assert "Something went wrong" in caplog.text
        assert all(r.exc_info is None for r in caplog.records)

    def test_default_title_is_error(self, monkeypatch):
        mock_mb = _patch_qmessagebox(monkeypatch)
        error_dialog.show_error(None, "ctx")
        assert mock_mb.critical.call_args[0][1] == "Error"
