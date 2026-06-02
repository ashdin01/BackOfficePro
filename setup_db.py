"""
Run this once to create a fresh blank database.
Automatically called by main.py if no database exists.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from database import init_db
from database.migrations import apply_migrations

def setup():
    data_dir = os.path.join(BASE_DIR, 'data')
    os.makedirs(data_dir, exist_ok=True)
    init_db()
    apply_migrations()
    print("✅ Fresh database created")

if __name__ == "__main__":
    setup()
