from database.connection import get_connection


def apply_migrations():
    conn = get_connection()
    version = conn.execute(
        "SELECT value FROM settings WHERE key='schema_version'"
    ).fetchone()
    current = int(version['value']) if version else 1

    if current < 2:
        migrate_v2(conn)
        print("Migration v2 applied: barcode_aliases")

    conn.close()


def migrate_v2(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS barcode_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias_barcode TEXT NOT NULL UNIQUE,
            master_barcode TEXT NOT NULL REFERENCES products(barcode),
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("UPDATE settings SET value = '2' WHERE key = 'schema_version'")
    conn.commit()
