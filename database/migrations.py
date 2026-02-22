"""
Migrations module — handles schema changes over time.
Run apply_migrations() on app startup after init_db().
Add new migrations to the MIGRATIONS list as the schema evolves.
"""

from database.connection import get_connection

MIGRATIONS = [
    # Each entry is (version, sql)
    # Example:
    # (1, "ALTER TABLE products ADD COLUMN location TEXT;"),
]


def get_current_version(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL DEFAULT 0)"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] if row[0] is not None else 0


def apply_migrations():
    conn = get_connection()
    current = get_current_version(conn)
    for version, sql in MIGRATIONS:
        if version > current:
            conn.execute(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
            print(f"Applied migration v{version}")
    conn.close()
