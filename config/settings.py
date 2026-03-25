import os
import sys

# Detect if running as PyInstaller bundle
if getattr(sys, 'frozen', False):
    # Running as compiled exe — use directory containing the exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as normal Python script
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Database — stored next to the exe on Windows, in data/ on Linux
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DATA_DIR, 'backoffice.db')

# App info
APP_NAME    = "BackOfficePro"
APP_VERSION = "1.0.0"
from version import VERSION as APP_VERSION
