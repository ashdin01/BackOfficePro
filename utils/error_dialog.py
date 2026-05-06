import logging
from PyQt6.QtWidgets import QMessageBox


def show_error(parent, context: str, exc: Exception = None, title: str = "Error") -> None:
    """Log exc with full traceback, then show a clean error dialog.

    Users see a plain context sentence plus one-line detail.
    The full traceback goes to the log file in BackOfficeLogs/.
    """
    if exc is not None:
        logging.error("%s: %s", context, exc, exc_info=exc)
        text = f"{context}\n\nDetail: {exc}"
    else:
        logging.error(context)
        text = context
    QMessageBox.critical(parent, title, text)
