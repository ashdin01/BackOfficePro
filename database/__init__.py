from database.connection import get_connection
from database.schema import SCHEMA


def init_db():
    """Create all tables on first run."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
