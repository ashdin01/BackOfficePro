"""Self-signed TLS certificate management for the BackOfficePro API server.

Generates a 10-year RSA-2048 cert with SANs covering localhost and every LAN IP
detected at startup. The cert/key pair is written to the user's config directory
and reused across restarts so clients only need to trust it once.

Usage:
    from utils.tls import get_or_create_cert, serve_tls
    cert_path, key_path = get_or_create_cert()
    serve_tls(app, host, port)
"""
import ipaddress
import logging
import os
import socket
import ssl
import datetime
from pathlib import Path
from wsgiref.simple_server import make_server, WSGIServer
from socketserver import ThreadingMixIn


_CERT_DIR = Path(os.environ.get(
    "BACKOFFICE_CERT_DIR",
    os.path.join(os.path.expanduser("~"), ".backoffice_pro"),
))
_CERT_FILE = _CERT_DIR / "api_server.crt"
_KEY_FILE  = _CERT_DIR / "api_server.key"

_CERT_VALIDITY_DAYS = 3650  # 10 years


def _lan_ips() -> list[str]:
    """Return all non-loopback IPv4 addresses on this machine."""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0]
            try:
                parsed = ipaddress.ip_address(addr)
                if parsed.version == 4 and not parsed.is_loopback:
                    ips.append(addr)
            except ValueError:
                pass
    except Exception:
        pass
    return list(dict.fromkeys(ips))  # deduplicate, preserve order


def _generate_self_signed(cert_path: Path, key_path: Path) -> None:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    san_entries: list = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    for ip in _lan_ips():
        try:
            san_entries.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except ValueError:
            pass

    hostname = socket.gethostname()
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"BackOfficePro ({hostname})"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BackOfficePro"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    # Restrict key file permissions on POSIX
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass
    logging.info("Generated self-signed TLS cert: %s (SANs: %s)",
                 cert_path, [str(s) for s in san_entries])


def get_or_create_cert() -> tuple[str, str]:
    """Return (cert_path, key_path), generating the pair if either file is missing."""
    if not _CERT_FILE.exists() or not _KEY_FILE.exists():
        logging.info("TLS certificate not found — generating self-signed cert")
        _generate_self_signed(_CERT_FILE, _KEY_FILE)
    return str(_CERT_FILE), str(_KEY_FILE)


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """Multi-threaded WSGI server (stdlib) with TLS wrapping."""
    daemon_threads = True


def serve_tls(flask_app, host: str, port: int, threads: int = 4) -> None:
    """Serve *flask_app* over HTTPS using a self-signed certificate.

    Falls back to plain HTTP if the cryptography package is unavailable so
    development environments without it still work.
    """
    try:
        cert_path, key_path = get_or_create_cert()
    except ImportError:
        logging.warning(
            "cryptography package not installed — serving plain HTTP. "
            "Run: pip install cryptography"
        )
        from waitress import serve as _waitress_serve
        _waitress_serve(flask_app, host=host, port=port, threads=threads)
        return

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

    httpd = make_server(host, port, flask_app, server_class=_ThreadingWSGIServer)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    logging.info("BackOfficePro API → https://%s:%d  (TLS, self-signed)", host, port)
    print(f"BackOfficePro API → https://{host}:{port}")
    print(f"TLS cert: {cert_path}")
    print("API key loaded from keyring/DB. Pass as header: X-API-Key: <key>")
    httpd.serve_forever()
