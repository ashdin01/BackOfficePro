import logging
import os
import sqlite3
from datetime import datetime

from config.settings import DATABASE_PATH
import models.settings as settings_model

_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "BackOfficeBackups")
_KEEP_COUNT = 30
_REQUIRED_TABLES = {"products", "suppliers", "departments", "purchase_orders"}


def get_backup_dir() -> str:
    return _BACKUP_DIR


def do_backup(dest_path) -> tuple[bool, str]:
    """Snapshot the live DB to dest_path using the SQLite online backup API.
    Returns (success: bool, message: str)."""
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        src  = sqlite3.connect(DATABASE_PATH)
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
        size = os.path.getsize(dest_path)
        logging.info("Backup created: %s (%.1f KB)", dest_path, size / 1024)
        return True, f"Backup saved:\n{dest_path}\n({size/1024:.1f} KB)"
    except Exception as e:
        logging.error("Backup failed to %s: %s", dest_path, e)
        return False, str(e)


def silent_auto_backup() -> str | None:
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
        logging.exception("backup pruning failed")
    return dest


def get_backup_email() -> str:
    """Return the backup_email setting value, or '' if not set."""
    return (settings_model.get_setting('backup_email') or '').strip()


def get_last_backup_time() -> datetime | None:
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
        logging.exception("get_last_backup_time failed")
    return None


def validate_backup_file(path) -> tuple[bool, set]:
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


def restore_backup(src_path) -> None:
    """
    Restore src_path over the live database using the SQLite backup API.
    Re-validates required tables on the same connection used to copy,
    eliminating any window between the caller's validation and the write.
    Raises RuntimeError on validation failure, or any sqlite3 error on copy failure.

    Closes the calling thread's pooled connection before writing, then
    invalidates all other threads' connections so they reopen fresh handles
    to the restored database on their next query.
    """
    from database.connection import close_thread_connection, invalidate_all_connections

    size_kb = os.path.getsize(src_path) / 1024
    logging.warning(
        "Database restore initiated: source=%s (%.1f KB) -> dest=%s",
        src_path, size_kb, DATABASE_PATH,
    )

    # Release our own pooled handle before overwriting the file.
    close_thread_connection()

    src = sqlite3.connect(src_path)
    try:
        tables = {r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        missing = _REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(
                f"Backup file failed re-validation (missing tables: {', '.join(sorted(missing))})"
            )
        dest = sqlite3.connect(DATABASE_PATH)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()

    # Invalidate every thread's cached connection so the next get_connection()
    # call opens a fresh handle to the restored database.
    invalidate_all_connections()

    logging.warning("Database restore complete: %s", src_path)
