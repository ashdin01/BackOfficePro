"""Single source of truth for the REST API key.

Primary store is the OS keychain (keyring); the settings DB is a plaintext
fallback for environments where keyring is unavailable. Installs that still
have the key in the plaintext DB are migrated to keyring on first resolve
and the DB copy is cleared.

Both the API server and the desktop Settings screen MUST resolve the key
through this module. Resolving it independently lets the two disagree: on a
machine with a working keyring (e.g. Windows Credential Manager) the server
migrates the key out of the DB, and a screen that reads only the DB then
shows — or regenerates — a key the server will never accept.
"""
import logging
import secrets

import models.settings as settings_model
from utils.secret_store import get_secret, set_secret


def resolve_api_key() -> str:
    """Return the stored API key, generating one on first use."""
    key = get_secret("api_key")
    if key:
        return key

    # Migration path: key may still be in the plaintext settings table.
    key = settings_model.get_setting("api_key", "")
    if key:
        set_secret("api_key", key)
        if get_secret("api_key"):
            settings_model.set_setting("api_key", "")  # clear plaintext copy
        else:
            logging.warning(
                "Keyring unavailable — API key migrated from DB but could not be stored securely"
            )
        return key

    key = secrets.token_hex(32)
    store_api_key(key)
    return key


def store_api_key(key: str) -> None:
    """Persist the API key: keyring preferred, plaintext settings DB as fallback."""
    set_secret("api_key", key)
    if get_secret("api_key") == key:
        settings_model.set_setting("api_key", "")  # clear any plaintext copy
    else:
        # Keyring unavailable — fall back to plaintext settings table so the
        # key survives process restarts (better than silently going ephemeral).
        settings_model.set_setting("api_key", key)
        logging.warning(
            "Keyring unavailable: API key stored in plaintext settings table. "
            "Install a keyring backend (e.g. python-keyring with SecretService) "
            "for better security."
        )
