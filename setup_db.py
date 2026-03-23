"""
Run this once to create a fresh blank database.
Automatically called by main.py if no database exists.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from database.connection import get_connection
from database.schema import SCHEMA
from database.migrations import run_migrations

def setup():
    data_dir = os.path.join(BASE_DIR, 'data')
    os.makedirs(data_dir, exist_ok=True)
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    run_migrations(conn)
    conn.close()
    print("✅ Fresh database created")

if __name__ == "__main__":
    setup()
