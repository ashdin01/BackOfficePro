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
