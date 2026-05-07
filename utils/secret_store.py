"""
Secure credential storage for BackOfficePro.
Uses the OS keystore (Windows Credential Manager, macOS Keychain,
Linux Secret Service) via the keyring library.
"""
import logging

_SERVICE = "BackOfficePro"


def get_secret(key: str) -> str:
    """Return the stored secret for key, or '' if not set."""
    try:
        import keyring
        value = keyring.get_password(_SERVICE, key)
        return value or ""
    except Exception as e:
        logging.warning("secret_store.get_secret(%r) failed: %s", key, e)
        return ""


def set_secret(key: str, value: str) -> None:
    """Store value in the OS keystore under key."""
    try:
        import keyring
        if value:
            keyring.set_password(_SERVICE, key, value)
        else:
            try:
                keyring.delete_password(_SERVICE, key)
            except Exception:
                pass
    except Exception as e:
        logging.warning("secret_store.set_secret(%r) failed: %s", key, e)
