"""
Thread-local database connection.

Each OS thread gets one sqlite3.Connection for its lifetime, so PRAGMAs
are executed once rather than on every model-function call.

Model functions call get_connection() then conn.release() when done.
release() rolls back any uncommitted transaction without disconnecting,
keeping the thread-local connection alive across calls.

If DATABASE_PATH changes (which happens in tests via monkeypatch), the
cached connection is replaced automatically.
"""
import logging
import sqlite3
import threading
import time

from config.settings import DATABASE_PATH  # module-level name; monkeypatched in tests


_local = threading.local()

_LOCK_RETRIES = 3    # extra attempts after the SQLite timeout expires
_LOCK_BACKOFF  = 0.1 # seconds; multiplied by attempt index (0.1 s, 0.2 s, 0.3 s)

# Incremented by invalidate_all_connections(). Each thread stores the generation
# its connection was opened under; a mismatch triggers a reconnect.
_generation: int = 0


def _retry_on_lock(fn, *args):
    """Call fn(*args), retrying up to _LOCK_RETRIES times on 'database is locked'."""
    for attempt in range(_LOCK_RETRIES + 1):
        try:
            return fn(*args)
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == _LOCK_RETRIES:
                raise
            delay = _LOCK_BACKOFF * (attempt + 1)
            logging.warning(
                "SQLite lock contention (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, _LOCK_RETRIES, delay, e,
            )
            time.sleep(delay)


class _Connection:
    """
    Proxy around sqlite3.Connection whose close() rolls back instead of
    disconnecting, keeping the thread-local connection alive across calls.

    execute() and executemany() retry automatically on 'database is locked'
    errors (WAL contention between the UI thread and the Flask API thread).
    Each retry is logged at WARNING so lock events are visible in the log file.
    """

    def __init__(self, raw: sqlite3.Connection):
        object.__setattr__(self, '_raw', raw)

    def release(self):
        """Roll back any uncommitted transaction without disconnecting."""
        try:
            object.__getattribute__(self, '_raw').rollback()
        except Exception:
            pass

    def close(self):
        """Alias for release() — kept for backward compatibility."""
        self.release()

    def execute(self, sql, parameters=()):
        raw = object.__getattribute__(self, '_raw')
        return _retry_on_lock(raw.execute, sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        raw = object.__getattribute__(self, '_raw')
        return _retry_on_lock(raw.executemany, sql, seq_of_parameters)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_raw'), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, '_raw'), name, value)


def get_connection() -> _Connection:
    """
    Return the thread-local connection, creating or replacing it when needed.

    The connection is replaced when DATABASE_PATH has changed since the last
    call (test isolation: each test fixture points to a fresh tmp database),
    or when invalidate_all_connections() has been called (e.g. after a restore).
    """
    current_path = DATABASE_PATH  # read the (possibly monkeypatched) module global
    current_gen  = _generation

    cached: _Connection | None = getattr(_local, 'conn',       None)
    cached_path: str | None    = getattr(_local, 'path',       None)
    cached_gen:  int           = getattr(_local, 'generation', -1)

    if cached is None or cached_path != current_path or cached_gen != current_gen:
        if cached is not None:
            try:
                object.__getattribute__(cached, '_raw').close()
            except Exception:
                pass

        raw = sqlite3.connect(current_path, timeout=10)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
        raw.execute("PRAGMA synchronous = NORMAL")

        _local.conn       = _Connection(raw)
        _local.path       = current_path
        _local.generation = current_gen

    return _local.conn


def close_thread_connection():
    """
    Fully close and discard the thread-local connection.
    Call this when a worker thread finishes to release the file handle.
    Not required on the main thread (connection lives for the process).
    """
    cached = getattr(_local, 'conn', None)
    if cached is not None:
        try:
            object.__getattribute__(cached, '_raw').close()
        except Exception:
            pass
        _local.conn = None
        _local.path = None


def invalidate_all_connections():
    """
    Force every thread to reopen its connection on the next get_connection() call.
    Call this after a database restore so no thread is left with a stale handle
    to the pre-restore database content.
    """
    global _generation
    _generation += 1
