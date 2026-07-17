import os
import sys
import shutil
import logging

# Detect if running as PyInstaller bundle
if getattr(sys, 'frozen', False):
    # Executable lives inside the onedir folder — data sits alongside it
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Pre-%LOCALAPPDATA% releases stored the database next to the .exe. Installs
# commonly land in C:\Program Files, which a standard (non-admin) Windows
# account can't write to — so frozen Windows builds now use %LOCALAPPDATA%
# instead, which is always writable by the running user regardless of where
# the app itself is installed.
_LEGACY_DATA_DIR = os.path.join(BASE_DIR, 'data')


def _migrate_legacy_data_dir(new_dir: str) -> None:
    """
    One-time move of an existing store's data from the legacy exe-relative
    location to new_dir, so upgrading in place doesn't look like the
    database vanished.

    Keyed off backoffice.db specifically (not just new_dir existing) so a
    prior migration that was interrupted partway through gets retried
    instead of silently leaving an empty database in place.
    """
    if os.path.exists(os.path.join(new_dir, 'backoffice.db')):
        return  # already migrated
    if not os.path.isdir(_LEGACY_DATA_DIR):
        return  # fresh install — nothing to migrate
    try:
        os.makedirs(os.path.dirname(new_dir), exist_ok=True)
        if os.path.isdir(new_dir):
            os.rmdir(new_dir)  # empty leftover from a prior failed attempt
        shutil.move(_LEGACY_DATA_DIR, new_dir)
        logging.info("Migrated data folder %s -> %s", _LEGACY_DATA_DIR, new_dir)
    except Exception:
        logging.exception("Data folder migration to %s failed", new_dir)


# Database and images. Dev runs (not frozen) keep using the repo-root
# 'data' folder regardless of OS.
if getattr(sys, 'frozen', False) and sys.platform == 'win32' and os.environ.get('LOCALAPPDATA'):
    DATA_DIR = os.path.join(os.environ['LOCALAPPDATA'], 'BackOfficePro', 'data')
    _migrate_legacy_data_dir(DATA_DIR)
else:
    DATA_DIR = _LEGACY_DATA_DIR

os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DATA_DIR, 'backoffice.db')

# App info — version pulled from version.py (single source of truth)
APP_NAME = "BackOfficePro"
try:
    from version import VERSION as APP_VERSION
except ImportError:
    APP_VERSION = "unknown"

# Each entry maps a display name to its database filename inside DATA_DIR.
# Add more stores here; a single entry skips the picker entirely.
STORES = [
    {"name": "Little Red Apple", "db": "backoffice.db"},
    {"name": "Harcourt Cider",   "db": "harcourt_cider.db"},
]
# Set at runtime by _pick_store() in main.py before the login screen opens.
ACTIVE_STORE_NAME = ""
