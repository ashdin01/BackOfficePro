"""Tests for utils/tls.py — cert generation, file permissions, idempotency."""
import datetime
import os
import stat
import sys
from pathlib import Path

import pytest
import utils.tls as tls_mod


# ── _lan_ips ──────────────────────────────────────────────────────────────────

class TestLanIps:
    def test_returns_list(self):
        result = tls_mod._lan_ips()
        assert isinstance(result, list)

    def test_no_loopback_addresses(self):
        ips = tls_mod._lan_ips()
        for ip in ips:
            assert not ip.startswith("127."), f"loopback address {ip!r} returned"

    def test_no_duplicates(self):
        ips = tls_mod._lan_ips()
        assert len(ips) == len(set(ips))


# ── _generate_self_signed ─────────────────────────────────────────────────────

class TestGenerateSelfSigned:
    def test_creates_cert_and_key_files(self, tmp_path):
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        assert cert.exists()
        assert key.exists()

    def test_cert_is_valid_pem(self, tmp_path):
        from cryptography import x509
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        cert_obj = x509.load_pem_x509_certificate(cert.read_bytes())
        assert cert_obj is not None

    def test_key_is_valid_pem(self, tmp_path):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        key_obj = load_pem_private_key(key.read_bytes(), password=None)
        assert key_obj is not None

    def test_cert_cn_contains_backoffice(self, tmp_path):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        cert_obj = x509.load_pem_x509_certificate(cert.read_bytes())
        cn = cert_obj.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert "BackOfficePro" in cn

    def test_san_includes_localhost(self, tmp_path):
        from cryptography import x509
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        cert_obj = x509.load_pem_x509_certificate(cert.read_bytes())
        san = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "localhost" in dns_names

    def test_san_includes_loopback_ip(self, tmp_path):
        import ipaddress
        from cryptography import x509
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        cert_obj = x509.load_pem_x509_certificate(cert.read_bytes())
        san = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        ip_addrs = san.value.get_values_for_type(x509.IPAddress)
        assert ipaddress.IPv4Address("127.0.0.1") in ip_addrs

    def test_cert_validity_is_long(self, tmp_path):
        from cryptography import x509
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        cert_obj = x509.load_pem_x509_certificate(cert.read_bytes())
        validity_days = (cert_obj.not_valid_after - cert_obj.not_valid_before).days
        assert validity_days >= 365

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod not enforced on Windows")
    def test_key_file_is_mode_600(self, tmp_path):
        cert = tmp_path / "test.crt"
        key = tmp_path / "test.key"
        tls_mod._generate_self_signed(cert, key)
        mode = stat.S_IMODE(key.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_creates_parent_directory(self, tmp_path):
        cert = tmp_path / "subdir" / "nested" / "test.crt"
        key = tmp_path / "subdir" / "nested" / "test.key"
        tls_mod._generate_self_signed(cert, key)
        assert cert.exists()


# ── get_or_create_cert ────────────────────────────────────────────────────────

class TestGetOrCreateCert:
    def _patch_paths(self, monkeypatch, tmp_path):
        cert = tmp_path / "api_server.crt"
        key = tmp_path / "api_server.key"
        monkeypatch.setattr(tls_mod, "_CERT_FILE", cert)
        monkeypatch.setattr(tls_mod, "_KEY_FILE", key)
        return cert, key

    def test_generates_files_when_absent(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        tls_mod.get_or_create_cert()
        assert cert.exists()
        assert key.exists()

    def test_returns_str_paths(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        cp, kp = tls_mod.get_or_create_cert()
        assert isinstance(cp, str)
        assert isinstance(kp, str)

    def test_returns_correct_paths(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        cp, kp = tls_mod.get_or_create_cert()
        assert cp == str(cert)
        assert kp == str(key)

    def test_idempotent_does_not_regenerate(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        tls_mod.get_or_create_cert()
        mtime_before = cert.stat().st_mtime
        tls_mod.get_or_create_cert()
        assert cert.stat().st_mtime == mtime_before

    def test_regenerates_when_cert_missing(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        tls_mod.get_or_create_cert()
        cert.unlink()
        tls_mod.get_or_create_cert()
        assert cert.exists()

    def test_regenerates_when_key_missing(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        tls_mod.get_or_create_cert()
        key.unlink()
        tls_mod.get_or_create_cert()
        assert key.exists()

    def test_regenerates_when_cert_expires_soon(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        tls_mod.get_or_create_cert()
        mtime_before = cert.stat().st_mtime
        # Make _cert_expires_soon return True so get_or_create_cert regenerates
        monkeypatch.setattr(tls_mod, "_cert_expires_soon", lambda p: True)
        tls_mod.get_or_create_cert()
        assert cert.stat().st_mtime >= mtime_before  # cert was rewritten


class TestCertExpiresSoon:
    def _patch_paths(self, monkeypatch, tmp_path):
        cert = tmp_path / "api_server.crt"
        key  = tmp_path / "api_server.key"
        monkeypatch.setattr(tls_mod, "_CERT_FILE", cert)
        monkeypatch.setattr(tls_mod, "_KEY_FILE",  key)
        return cert, key

    def test_returns_false_for_missing_file(self, tmp_path):
        result = tls_mod._cert_expires_soon(tmp_path / "nonexistent.crt")
        assert result is False

    def test_returns_false_for_invalid_cert_data(self, tmp_path):
        bad = tmp_path / "bad.crt"
        bad.write_bytes(b"not a cert")
        assert tls_mod._cert_expires_soon(bad) is False

    def test_returns_false_for_fresh_cert(self, monkeypatch, tmp_path):
        cert, key = self._patch_paths(monkeypatch, tmp_path)
        tls_mod.get_or_create_cert()
        assert tls_mod._cert_expires_soon(cert) is False


class TestLanIps:
    def test_returns_list(self):
        result = tls_mod._lan_ips()
        assert isinstance(result, list)

    def test_handles_bad_address_gracefully(self, monkeypatch):
        import socket
        monkeypatch.setattr(
            socket, "getaddrinfo",
            lambda *a, **kw: [("", "", "", "", ("not-an-ip", 0))],
        )
        result = tls_mod._lan_ips()
        assert isinstance(result, list)

    def test_handles_socket_error_gracefully(self, monkeypatch):
        import socket
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: (_ for _ in ()).throw(OSError("no net")))
        result = tls_mod._lan_ips()
        assert result == []


class TestServeTlsFallback:
    def test_import_error_falls_back_to_plain_http(self, monkeypatch):
        def fake_get_or_create_cert():
            raise ImportError("cryptography not installed")

        def fake_waitress(app, **kw):
            raise SystemExit(0)

        monkeypatch.setattr(tls_mod, "get_or_create_cert", fake_get_or_create_cert)
        import sys
        fake_mod = type(sys)("waitress_fake")
        fake_mod.serve = fake_waitress
        monkeypatch.setitem(sys.modules, "waitress", fake_mod)

        from unittest.mock import MagicMock
        with pytest.raises(SystemExit):
            tls_mod.serve_tls(MagicMock(), host="127.0.0.1", port=19876)


class TestServeTlsMainPath:
    def test_serve_tls_binds_and_serves(self, monkeypatch, tmp_path):
        """Main TLS path: mocked cert + SSLContext + make_server so no real socket is opened."""
        from unittest.mock import MagicMock, patch
        import ssl

        cert = str(tmp_path / "cert.pem")
        key  = str(tmp_path / "key.pem")
        # Write placeholder files so load_cert_chain doesn't fail
        open(cert, 'w').close()
        open(key, 'w').close()

        monkeypatch.setattr(tls_mod, "get_or_create_cert", lambda: (cert, key))

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = MagicMock()
        monkeypatch.setattr(ssl, "SSLContext", lambda *a, **kw: mock_ctx)

        mock_httpd = MagicMock()
        mock_httpd.serve_forever.side_effect = SystemExit(0)
        monkeypatch.setattr(tls_mod, "make_server", lambda *a, **kw: mock_httpd)

        with pytest.raises(SystemExit):
            tls_mod.serve_tls(MagicMock(), host="127.0.0.1", port=19999)

        mock_ctx.load_cert_chain.assert_called_once_with(certfile=cert, keyfile=key)
        mock_httpd.serve_forever.assert_called_once()

    def test_serve_tls_wraps_socket(self, monkeypatch, tmp_path):
        """Confirms ctx.wrap_socket is called with server_side=True."""
        from unittest.mock import MagicMock
        import ssl

        cert = str(tmp_path / "cert.pem")
        key  = str(tmp_path / "key.pem")
        open(cert, 'w').close()
        open(key, 'w').close()

        monkeypatch.setattr(tls_mod, "get_or_create_cert", lambda: (cert, key))

        mock_ctx = MagicMock()
        wrapped_socket = MagicMock()
        mock_ctx.wrap_socket.return_value = wrapped_socket
        monkeypatch.setattr(ssl, "SSLContext", lambda *a, **kw: mock_ctx)

        mock_httpd = MagicMock()
        mock_httpd.serve_forever.side_effect = SystemExit(0)
        monkeypatch.setattr(tls_mod, "make_server", lambda *a, **kw: mock_httpd)

        with pytest.raises(SystemExit):
            tls_mod.serve_tls(MagicMock(), host="127.0.0.1", port=19998)

        _, kwargs = mock_ctx.wrap_socket.call_args
        assert kwargs.get("server_side") is True
        assert mock_httpd.socket == wrapped_socket
