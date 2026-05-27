"""
Thread-local audit context.

Call set_context() once per request/event to record who is performing an
operation and from where.  Model functions read get_user() / get_source()
when writing to stock_movements so every inventory change is attributable.

Sources:
    'UI'  — desktop PyQt6 application (logged-in user)
    'API' — Flask REST API (POS / Android client)
"""
import threading

_local = threading.local()


def set_context(user: str, source: str = 'UI') -> None:
    """Set the current thread's audit identity."""
    _local.user = user
    _local.source = source


def get_user() -> str:
    """Return the current user, or '' if context has not been set."""
    return getattr(_local, 'user', '')


def get_source() -> str:
    """Return the current source ('UI' or 'API'), or '' if not set."""
    return getattr(_local, 'source', '')
