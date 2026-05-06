import os
import sys

# Detect if running as PyInstaller bundle
if getattr(sys, 'frozen', False):
    # Executable lives inside the onedir folder — data sits alongside it
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Database and images — writable folder next to the exe (or repo root in dev)
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DATA_DIR, 'backoffice.db')

# App info — version pulled from version.py (single source of truth)
APP_NAME = "BackOfficePro"
try:
    from version import VERSION as APP_VERSION
except ImportError:
    APP_VERSION = "unknown"
