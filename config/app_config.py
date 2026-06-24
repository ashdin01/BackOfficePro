"""
Cross-store application config.

A handful of settings — currently just merged_login — must be readable
before any single store's database is chosen, so they can't live in the
per-store `settings` table (models/settings.py). They live instead in a
small JSON file alongside the store databases in DATA_DIR.
"""
import json
import logging
import os

from config.settings import DATA_DIR

_CONFIG_PATH = os.path.join(DATA_DIR, 'app_config.json')

_DEFAULTS = {
    "merged_login": True,
}


def _load() -> dict:
    if not os.path.isfile(_CONFIG_PATH):
        return dict(_DEFAULTS)
    try:
        with open(_CONFIG_PATH, 'r') as f:
            data = json.load(f)
        merged = dict(_DEFAULTS)
        merged.update(data)
        return merged
    except Exception:
        logging.warning("app_config.py: could not read %s, using defaults", _CONFIG_PATH, exc_info=True)
        return dict(_DEFAULTS)


def _save(data: dict):
    try:
        with open(_CONFIG_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        logging.error("app_config.py: could not write %s", _CONFIG_PATH, exc_info=True)


def get_merged_login() -> bool:
    return bool(_load().get("merged_login", True))


def set_merged_login(value: bool):
    data = _load()
    data["merged_login"] = bool(value)
    _save(data)
