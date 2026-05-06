import logging
import os
import shutil
import sqlite3
from datetime import datetime

from config.settings import DATABASE_PATH
from database.connection import get_connection

_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "BackOfficeBackups")
_KEEP_COUNT = 30
_REQUIRED_TABLES = {"products", "suppliers", "departments", "purchase_orders"}


def get_backup_dir():
    return _BACKUP_DIR


def do_backup(dest_path):
    """Copy the live DB to dest_path. Returns (success: bool, message: str)."""
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(DATABASE_PATH, dest_path)
        size = os.path.getsize(dest_path)
        return True, f"Backup saved:\n{dest_path}\n({size/1024:.1f} KB)"
    except Exception as e:
        return False, str(e)


def silent_auto_backup():
    """
    Create a timestamped backup, prune old ones beyond _KEEP_COUNT.
    Returns the dest path on success, None on failure.
    """
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(_BACKUP_DIR, f"supermarket_{ts}.db")
    ok, _ = do_backup(dest)
    if not ok:
        return None
    try:
        files = sorted(
            [os.path.join(_BACKUP_DIR, f)
             for f in os.listdir(_BACKUP_DIR) if f.endswith(".db")]
        )
        for old in files[:-_KEEP_COUNT]:
            os.remove(old)
    except Exception:
        pass
    return dest


def get_backup_email():
    """Return the backup_email setting value, or '' if not set."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='backup_email'"
        ).fetchone()
        return (row['value'] or '').strip() if row else ''
    except Exception as e:
        logging.error("Could not read backup_email setting: %s", e, exc_info=True)
        return ''
    finally:
        conn.close()


def get_last_backup_time():
    """
    Return the datetime of the most recent .db file in the backup dir, or None.
    """
    try:
        files = sorted(
            [f for f in os.listdir(_BACKUP_DIR) if f.endswith(".db")],
            reverse=True
        )
        if files:
            ts = files[0].replace("supermarket_", "").replace(".db", "")
            return datetime.strptime(ts, "%Y%m%d_%H%M%S")
    except Exception:
        pass
    return None


def validate_backup_file(path):
    """
    Check that path is a readable SQLite file with the required tables.
    Returns (valid: bool, missing_tables: set).
    """
    try:
        conn = sqlite3.connect(path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        missing = _REQUIRED_TABLES - tables
        return (len(missing) == 0), missing
    except Exception as e:
        raise RuntimeError(f"Could not read file: {e}") from e


def restore_backup(src_path):
    """
    Copy src_path over the live database. Raises on failure.
    Call validate_backup_file first.
    """
    shutil.copy2(src_path, DATABASE_PATH)
