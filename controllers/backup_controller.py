import logging
import os
import re
import sqlite3
from datetime import datetime

from config.settings import DATABASE_PATH
import models.settings as settings_model

_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "BackOfficeBackups")
_KEEP_COUNT = 30
_REQUIRED_TABLES = {"products", "suppliers", "departments", "purchase_orders"}
_BACKUP_RE = re.compile(r'^supermarket_(\d{8}_\d{6})\.db$')


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


def get_backup_local_path() -> str:
    """Return the extra backup folder setting (e.g. a USB drive), or '' if not set."""
    return (settings_model.get_setting('backup_local_path') or '').strip()


def backup_to_local_path() -> tuple[bool, str]:
    """Snapshot the live DB into the user-configured extra backup folder.

    This is an additional destination on top of the standard ~/BackOfficeBackups
    auto-backup — typically a USB stick or external drive. Prunes only files
    matching the supermarket_<timestamp>.db naming pattern beyond _KEEP_COUNT,
    so anything else the user keeps in that folder is never touched.

    Returns (success, message). An unconfigured path is reported as failure so
    callers can distinguish it; check get_backup_local_path() first if the
    feature being disabled is not an error in your context.
    """
    folder = get_backup_local_path()
    if not folder:
        return False, "No backup folder configured."
    if not os.path.isdir(folder):
        return False, (f"Backup folder not found:\n{folder}\n\n"
                       "Is the USB / external drive plugged in?")

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(folder, f"supermarket_{ts}.db")
    ok, msg = do_backup(dest)
    if not ok:
        return False, msg

    try:
        ours = sorted(f for f in os.listdir(folder) if _BACKUP_RE.match(f))
        for old in ours[:-_KEEP_COUNT]:
            os.remove(os.path.join(folder, old))
    except Exception:
        logging.exception("local-path backup pruning failed")
    return True, msg


def get_last_backup_time() -> datetime | None:
    """
    Return the datetime of the most recent standard backup in the backup dir,
    or None. PRE_RESTORE_ and other non-standard filenames are ignored.
    """
    try:
        timestamps = [
            m.group(1)
            for f in os.listdir(_BACKUP_DIR)
            if (m := _BACKUP_RE.match(f))
        ]
        if timestamps:
            return datetime.strptime(max(timestamps), "%Y%m%d_%H%M%S")
    except Exception:
        logging.exception("get_last_backup_time failed")
    return None


def validate_backup_file(path) -> tuple[bool, set]:
    """
    Check that path is a readable SQLite file with the required tables and
    a schema_version entry in settings, confirming it is a BackOfficePro database.
    Returns (valid: bool, missing_tables: set).
    """
    try:
        conn = sqlite3.connect(path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        missing = _REQUIRED_TABLES - tables
        if not missing:
            # v54+: version lives in db_meta; pre-v54: it lives in settings.
            has_version = (
                ('db_meta' in tables and
                 conn.execute("SELECT version FROM db_meta").fetchone() is not None)
                or
                ('settings' in tables and
                 conn.execute(
                     "SELECT value FROM settings WHERE key='schema_version'"
                 ).fetchone() is not None)
            )
            if not has_version:
                missing.add('schema version marker')
        conn.close()
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

    # Bring a potentially older backup up to the current schema.
    from database.migrations import apply_migrations
    apply_migrations()
