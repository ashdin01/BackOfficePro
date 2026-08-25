"""Open a file with the OS default application (the app that owns
double-click, e.g. the default PDF viewer) — same platform dispatch used
inline for PDF exports across the app (PO PDFs, AR statements/invoices)."""
import os
import subprocess
import sys


def open_with_default_app(path: str) -> None:
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])
