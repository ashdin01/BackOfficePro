from PyQt6.QtCore import QObject, pyqtSignal


class _StockEvents(QObject):
    """Process-wide signal fired whenever stock_on_hand changes.

    Any screen that displays stock on hand can subscribe to `changed`
    instead of relying on a hardcoded list of screens to poke. Safe to
    emit from a background thread (e.g. the ATRIA sync thread) — Qt
    marshals the signal to slots living on the GUI thread automatically.

    Does not cover writes from the REST API subprocess (POS terminals,
    Android stocktake app) — those cross a process boundary this signal
    can't reach, so screens exposed to that traffic need their own polling.
    """
    changed = pyqtSignal()


stock_events = _StockEvents()
