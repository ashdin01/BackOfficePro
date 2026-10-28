import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import quote

from config.settings import DATABASE_PATH
import models.settings as settings_model

_DEFAULT_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "BackOfficeBackups")
_BACKUP_DIR = _DEFAULT_BACKUP_DIR
_REQUIRED_TABLES = {"products", "suppliers", "departments", "purchase_orders"}
_BACKUP_RE = re.compile(r'^supermarket_(\d{8}_\d{6})\.db$')
_STAMP_FMT = "%Y%m%d_%H%M%S"

# Retention for standard (timestamped) backups — see select_backups_to_keep().
_KEEP_NEWEST = 3        # always keep the newest few, however many closes in a day
_KEEP_DAILY = 7         # newest backup of each of the last 7 days
_KEEP_WEEKLY = 4        # newest backup of each of the 4 weeks before that
_KEEP_MONTHLY = 12      # newest backup of each of the last 12 months

# Safety copies taken before a restore or migration. Not part of the rolling
# history above (get_last_backup_time ignores them); only the newest few are kept.
_SAFETY_PREFIXES = ("supermarket_PRE_RESTORE_", "supermarket_PRE_MIGRATION_")
_KEEP_SAFETY = 5
# A backup older than this is flagged as stale in the sidebar and triggers a
# scheduled backup while the app is open.
STALE_AFTER = timedelta(hours=24)


def get_backup_dir() -> str:
    return _BACKUP_DIR


def verify_backup(path) -> tuple[bool, str]:
    """Open path read-only and run SQLite's integrity_check.
    Returns (ok, detail); detail is 'ok' or the first problem reported.

    immutable=1 stops SQLite creating -wal/-shm sidecar files next to a backup
    that was saved in WAL mode (a plain read-only open leaves them behind)."""
    try:
        conn = sqlite3.connect(f"file:{quote(os.path.abspath(path))}?immutable=1", uri=True)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
        detail = str(rows[0][0]) if rows else "no result"
        return detail == "ok", detail
    except Exception as e:
        return False, str(e)


def do_backup(dest_path, src_path=None) -> tuple[bool, str]:
    """Snapshot the live DB (or src_path) to dest_path using the SQLite online
    backup API, then verify the copy with PRAGMA integrity_check. A copy that
    fails verification is deleted so it can never be mistaken for a good backup.
    Returns (success: bool, message: str)."""
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        src  = sqlite3.connect(src_path or DATABASE_PATH)
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
        ok, detail = verify_backup(dest_path)
        if not ok:
            try:
                os.remove(dest_path)
            except OSError:
                logging.exception("could not remove unverified backup %s", dest_path)
            raise RuntimeError(f"Backup failed integrity check: {detail}")
        size = os.path.getsize(dest_path)
        logging.info("Backup created: %s (%.1f KB)", dest_path, size / 1024)
        return True, f"Backup saved:\n{dest_path}\n({size/1024:.1f} KB)"
    except Exception as e:
        logging.error("Backup failed to %s: %s", dest_path, e)
        return False, str(e)


def select_backups_to_keep(stamps, now=None) -> set:
    """Decide which timestamped backups survive pruning (grandfather-father-son).

    stamps is an iterable of datetimes. Kept: the newest _KEEP_NEWEST; the newest
    of each of the last _KEEP_DAILY days; the newest of each of the following
    _KEEP_WEEKLY weeks; the newest of each of the last _KEEP_MONTHLY months.
    Retention is by age, not file count, so a day with many restarts can never
    push out the older history.
    """
    now = now or datetime.now()
    today = now.date()
    ordered = sorted(stamps, reverse=True)
    keep = set(ordered[:_KEEP_NEWEST])
    seen = set()
    for st in ordered:                       # newest first, so first hit per bucket wins
        age_days = (today - st.date()).days
        buckets = []
        if 0 <= age_days < _KEEP_DAILY:
            buckets.append(("d", age_days))
        elif _KEEP_DAILY <= age_days < _KEEP_DAILY + 7 * _KEEP_WEEKLY:
            buckets.append(("w", (age_days - _KEEP_DAILY) // 7))
        month_age = (today.year - st.year) * 12 + today.month - st.month
        if 0 <= month_age < _KEEP_MONTHLY:
            buckets.append(("m", month_age))
        for b in buckets:
            if b not in seen:
                seen.add(b)
                keep.add(st)
    return keep


def prune_backups(folder, now=None) -> int:
    """Apply the retention policy to the standard backups in folder.
    Only supermarket_<timestamp>.db files are considered; anything else in the
    folder is never touched. Returns the number of files removed."""
    found = {}
    for f in os.listdir(folder):
        m = _BACKUP_RE.match(f)
        if m:
            found[datetime.strptime(m.group(1), _STAMP_FMT)] = f
    keep = select_backups_to_keep(found, now)
    removed = 0
    for st, name in found.items():
        if st not in keep:
            os.remove(os.path.join(folder, name))
            removed += 1
    return removed


def prune_safety_backups(folder=None) -> int:
    """Keep only the newest _KEEP_SAFETY PRE_RESTORE and PRE_MIGRATION copies."""
    folder = folder or _BACKUP_DIR
    removed = 0
    try:
        for prefix in _SAFETY_PREFIXES:
            files = sorted(f for f in os.listdir(folder)
                           if f.startswith(prefix) and f.endswith(".db"))
            for old in files[:-_KEEP_SAFETY]:
                os.remove(os.path.join(folder, old))
                removed += 1
    except FileNotFoundError:
        pass
    except Exception:
        logging.exception("safety backup pruning failed")
    return removed


def pre_migration_backup(db_path, from_version) -> str:
    """Snapshot db_path before pending migrations run. Raises RuntimeError if the
    backup cannot be written and verified, so a migration never runs unprotected."""
    ts   = datetime.now().strftime(_STAMP_FMT)
    dest = os.path.join(_BACKUP_DIR, f"supermarket_PRE_MIGRATION_v{from_version}_{ts}.db")
    ok, msg = do_backup(dest, src_path=db_path)
    if not ok:
        raise RuntimeError(f"Could not back up the database before upgrading it: {msg}")
    prune_safety_backups()
    return dest


def silent_auto_backup() -> str | None:
    """
    Create a verified, timestamped backup and apply the retention policy.
    Returns the dest path on success, None on failure.
    """
    ts   = datetime.now().strftime(_STAMP_FMT)
    dest = os.path.join(_BACKUP_DIR, f"supermarket_{ts}.db")
    ok, _ = do_backup(dest)
    if not ok:
        return None
    try:
        prune_backups(_BACKUP_DIR)
    except Exception:
        logging.exception("backup pruning failed")
    prune_safety_backups()
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
    matching the supermarket_<timestamp>.db naming pattern (per the retention
    policy), so anything else the user keeps in that folder is never touched.

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
        prune_backups(folder)
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
            return datetime.strptime(max(timestamps), _STAMP_FMT)
    except FileNotFoundError:
        pass    # no backup folder yet — same as no backups
    except Exception:
        logging.exception("get_last_backup_time failed")
    return None


def is_backup_stale(now=None) -> bool:
    """True when there is no standard backup, or the newest is older than STALE_AFTER."""
    last = get_last_backup_time()
    return last is None or (now or datetime.now()) - last > STALE_AFTER


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
