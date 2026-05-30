"""Tests for utils/email_graph.py — Graph API email sending.

msal and keyring are not installed in this environment, so both are injected
as MagicMock objects into sys.modules before email_graph is imported.
"""
import sys
from unittest.mock import MagicMock, patch, call
import pytest

# ── Inject missing optional dependencies before importing the module ──────────

_mock_msal = MagicMock()
if "msal" not in sys.modules:
    sys.modules["msal"] = _mock_msal

_mock_keyring = MagicMock()
_mock_keyring.get_password.return_value = ""
if "keyring" not in sys.modules:
    sys.modules["keyring"] = _mock_keyring

import utils.email_graph as eg  # noqa: E402  (after sys.modules patch)

# ── Helpers ───────────────────────────────────────────────────────────────────

_FULL_SETTINGS = {
    "graph_client_id":     "test-client-id",
    "graph_tenant_id":     "test-tenant-id",
    "graph_client_secret": "test-secret",
    "graph_from_address":  "sender@example.com",
}

_EMPTY_SETTINGS = {
    "graph_client_id":     "",
    "graph_tenant_id":     "",
    "graph_client_secret": "",
    "graph_from_address":  "",
}


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


# ── _get_access_token ─────────────────────────────────────────────────────────

class TestGetAccessToken:
    def test_returns_token_on_success(self):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "tok123"}
        _mock_msal.ConfidentialClientApplication.return_value = mock_app
        token = eg._get_access_token("cid", "tid", "secret")
        assert token == "tok123"

    def test_raises_on_missing_access_token(self):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "error": "auth_failed",
            "error_description": "bad credentials",
        }
        _mock_msal.ConfidentialClientApplication.return_value = mock_app
        with pytest.raises(RuntimeError, match="Failed to obtain access token"):
            eg._get_access_token("cid", "tid", "bad")

    def test_uses_correct_scope(self):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "t"}
        _mock_msal.ConfidentialClientApplication.return_value = mock_app
        eg._get_access_token("cid", "tid", "secret")
        mock_app.acquire_token_for_client.assert_called_once_with(
            scopes=["https://graph.microsoft.com/.default"]
        )


# ── send_email ────────────────────────────────────────────────────────────────

class TestSendEmail:
    def test_raises_when_settings_incomplete(self):
        with patch.object(eg, "_load_graph_settings", return_value=_EMPTY_SETTINGS):
            with pytest.raises(RuntimeError, match="not fully configured"):
                eg.send_email("to@x.com", "Subject", "Body")

    def test_returns_true_on_202(self):
        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post",
                           return_value=_mock_response(202)):
                    result = eg.send_email("to@x.com", "Subj", "Body")
        assert result is True

    def test_raises_on_non_202_response(self):
        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post",
                           return_value=_mock_response(500, "Server Error")):
                    with pytest.raises(RuntimeError, match="HTTP 500"):
                        eg.send_email("to@x.com", "Subj", "Body")

    def test_includes_cc_when_provided(self):
        captured = {}
        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _mock_response(202)

        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post", side_effect=fake_post):
                    eg.send_email("to@x.com", "Subj", "Body", cc_address="cc@x.com")

        assert "ccRecipients" in captured["json"]["message"]
        assert captured["json"]["message"]["ccRecipients"][0]["emailAddress"]["address"] == "cc@x.com"

    def test_no_cc_key_when_cc_not_provided(self):
        captured = {}
        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _mock_response(202)

        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post", side_effect=fake_post):
                    eg.send_email("to@x.com", "Subj", "Body")

        assert "ccRecipients" not in captured["json"]["message"]

    def test_attaches_file_when_path_provided(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"PDF content here")
        captured = {}
        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _mock_response(202)

        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post", side_effect=fake_post):
                    eg.send_email("to@x.com", "Subj", "Body", attachment_path=str(pdf))

        attachments = captured["json"]["message"]["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["name"] == "test.pdf"
        assert attachments[0]["@odata.type"] == "#microsoft.graph.fileAttachment"

    def test_no_attachment_key_when_path_absent(self):
        captured = {}
        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _mock_response(202)

        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post", side_effect=fake_post):
                    eg.send_email("to@x.com", "Subj", "Body")

        assert "attachments" not in captured["json"]["message"]

    def test_sends_to_correct_graph_endpoint(self):
        captured = {}
        def fake_post(url, **kw):
            captured["url"] = url
            return _mock_response(202)

        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post", side_effect=fake_post):
                    eg.send_email("to@x.com", "Subj", "Body")

        assert "sender@example.com" in captured["url"]
        assert "sendMail" in captured["url"]

    def test_body_type_html_passed_through(self):
        captured = {}
        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _mock_response(202)

        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                with patch("utils.email_graph.requests.post", side_effect=fake_post):
                    eg.send_email("to@x.com", "Subj", "<b>Body</b>", body_type="HTML")

        assert captured["json"]["message"]["body"]["contentType"] == "HTML"


# ── test_graph_connection ─────────────────────────────────────────────────────

class TestGraphConnection:
    def test_returns_false_when_settings_missing(self):
        with patch.object(eg, "_load_graph_settings", return_value=_EMPTY_SETTINGS):
            ok, msg = eg.test_graph_connection()
        assert ok is False
        assert "fill in" in msg.lower()

    def test_returns_false_on_token_error(self):
        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token",
                              side_effect=RuntimeError("auth_failed")):
                ok, msg = eg.test_graph_connection()
        assert ok is False
        assert "auth_failed" in msg

    def test_returns_true_on_success(self):
        with patch.object(eg, "_load_graph_settings", return_value=_FULL_SETTINGS):
            with patch.object(eg, "_get_access_token", return_value="tok"):
                ok, msg = eg.test_graph_connection()
        assert ok is True
        assert "success" in msg.lower()


# ── send_purchase_order ───────────────────────────────────────────────────────

class TestSendPurchaseOrder:
    def test_subject_contains_po_number(self, test_db, db_conn, supplier_id):
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type) "
            "VALUES ('PO-EMAIL-001', ?, 'DRAFT', 'PO')",
            (supplier_id,),
        )
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='PO-EMAIL-001'"
        ).fetchone()["id"]

        captured = {}
        def fake_send(to_address, subject, body, attachment_path=None, **kw):
            captured.update({"to": to_address, "subject": subject, "body": body})
            return True

        with patch.object(eg, "send_email", side_effect=fake_send):
            result = eg.send_purchase_order(po_id, "supplier@example.com", "/tmp/po.pdf")

        assert result is True
        assert "PO-EMAIL-001" in captured["subject"]

    def test_body_mentions_supplier(self, test_db, db_conn, supplier_id):
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type) "
            "VALUES ('PO-EMAIL-002', ?, 'DRAFT', 'PO')",
            (supplier_id,),
        )
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='PO-EMAIL-002'"
        ).fetchone()["id"]

        captured = {}
        def fake_send(to_address, subject, body, **kw):
            captured["body"] = body
            return True

        with patch.object(eg, "send_email", side_effect=fake_send):
            eg.send_purchase_order(po_id, "supplier@example.com", "/tmp/po.pdf")

        assert "Test Supplier" in captured["body"]


# ── send_backup ───────────────────────────────────────────────────────────────

class TestSendBackup:
    def test_subject_contains_store_name(self, test_db, db_conn, tmp_path):
        db_conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('store_name', 'Apple Orchard')"
        )
        db_conn.commit()

        backup = tmp_path / "backup.db"
        backup.write_bytes(b"SQLite backup data")

        captured = {}
        def fake_send(to_address, subject, body, **kw):
            captured["subject"] = subject
            return True

        with patch.object(eg, "send_email", side_effect=fake_send):
            result = eg.send_backup(str(backup), "admin@example.com")

        assert result is True
        assert "Apple Orchard" in captured["subject"]

    def test_body_includes_filename(self, test_db, db_conn, tmp_path):
        backup = tmp_path / "mybackup.db"
        backup.write_bytes(b"data")

        captured = {}
        def fake_send(to_address, subject, body, **kw):
            captured["body"] = body
            return True

        with patch.object(eg, "send_email", side_effect=fake_send):
            eg.send_backup(str(backup), "admin@example.com")

        assert "mybackup.db" in captured["body"]
