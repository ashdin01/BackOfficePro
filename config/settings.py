import os

# Base directory of the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Database
DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'supermarket.db')

# App info
APP_NAME    = "Supermarket Back Office"
APP_VERSION = "1.0.0"
