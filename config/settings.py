import os

# Base directory of the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Database
DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'backoffice.db')

# App info
APP_NAME    = "BackOfficePro"
APP_VERSION = "1.0.0"
