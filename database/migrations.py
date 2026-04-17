import logging
from database.connection import get_connection

def apply_migrations():
    logging.info("apply_migrations() starting")
    conn = get_connection()
    try:
        version = conn.execute(
            "SELECT value FROM settings WHERE key='schema_version'"
        ).fetchone()
        current = int(version['value']) if version else 1
        logging.info(f"Current schema version: {current}")
    except Exception as e:
        logging.critical(f"Failed to read schema_version: {e}")
        conn.close()
        raise
    try:
        if current < 2:
            migrate_v2(conn)
            logging.info("Migration v2 applied: barcode_aliases")
        if current < 3:
            migrate_v3(conn)
            logging.info("Migration v3 applied: brand column")
        if current < 4:
            migrate_v4(conn)
            logging.info("Migration v4 applied: sku, supplier_sku columns")
        if current < 5:
            migrate_v5(conn)
            logging.info("Migration v5 applied: supplier abn, rep_name, rep_phone, order_minimum")
        if current < 6:
            migrate_v6(conn)
            logging.info("Migration v6 applied: product_groups table + group_id on products")
        if current < 7:
            migrate_v7(conn)
            logging.info("Migration v7 applied: sales_daily, plu_barcode_map")
        if current < 8:
            migrate_v8(conn)
            logging.info("Migration v8 applied: po_pdf_path setting")
        if current < 9:
            migrate_v9(conn)
            logging.info("Migration v9 applied: supplier email_orders, email_admin, email_accounts, email_rep")
        logging.info("apply_migrations() complete")
    except Exception as e:
        logging.critical(f"Migration failed: {e}", exc_info=True)
        raise
    finally:
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
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '2')")
    conn.commit()

def migrate_v3(conn):
    """Add brand column to products table."""
    try:
        conn.execute("ALTER TABLE products ADD COLUMN brand TEXT DEFAULT ''")
    except Exception:
        pass
    conn.execute("UPDATE settings SET value = '3' WHERE key = 'schema_version'")
    conn.commit()

def migrate_v4(conn):
    """Add sku and supplier_sku columns to products table."""
    try:
        conn.execute("ALTER TABLE products ADD COLUMN sku TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE products ADD COLUMN supplier_sku TEXT DEFAULT ''")
    except Exception:
        pass
    conn.execute("UPDATE settings SET value = '4' WHERE key = 'schema_version'")
    conn.commit()

def migrate_v5(conn):
    """Add abn, rep_name, rep_phone, order_minimum to suppliers table."""
    for col, typedef in [
        ("abn",           "TEXT DEFAULT ''"),
        ("rep_name",      "TEXT DEFAULT ''"),
        ("rep_phone",     "TEXT DEFAULT ''"),
        ("order_minimum", "REAL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE suppliers ADD COLUMN {col} {typedef}")
        except Exception:
            pass
    conn.execute("UPDATE settings SET value = '5' WHERE key = 'schema_version'")
    conn.commit()

def migrate_v6(conn):
    """Add product_groups table and group_id to products."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_groups (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            code          TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (department_id) REFERENCES departments(id),
            UNIQUE(department_id, code)
        )
    """)
    try:
        conn.execute("ALTER TABLE products ADD COLUMN group_id INTEGER REFERENCES product_groups(id)")
    except Exception:
        pass
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '6')")
    conn.commit()

def migrate_v7(conn):
    """Add all columns added during development session."""
    for col, typedef in [
        ("pack_qty",    "INTEGER DEFAULT 1"),
        ("pack_unit",   "TEXT DEFAULT 'EA'"),
        ("reorder_max", "REAL DEFAULT 0"),
        ("base_sku",    "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE products ADD COLUMN {col} {typedef}")
        except Exception:
            pass
    for col, typedef in [
        ("actual_cost", "REAL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE po_lines ADD COLUMN {col} {typedef}")
        except Exception:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plu_barcode_map (
            plu       INTEGER PRIMARY KEY,
            barcode   TEXT NOT NULL,
            mapped_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales_daily (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date     TEXT NOT NULL,
            plu           TEXT,
            plu_name      TEXT,
            sub_group     TEXT,
            weight_kg     REAL DEFAULT 0,
            quantity      REAL DEFAULT 0,
            nominal_price REAL DEFAULT 0,
            discount      REAL DEFAULT 0,
            rounding      REAL DEFAULT 0,
            sales_dollars REAL DEFAULT 0,
            sales_pct     REAL DEFAULT 0,
            imported_at   TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(sale_date, plu)
        )
    """)
    conn.execute("UPDATE products SET plu = sku WHERE sku IS NOT NULL AND sku != '' AND (plu IS NULL OR plu = '')")
    conn.execute("UPDATE products SET plu = base_sku WHERE base_sku IS NOT NULL AND base_sku != '' AND (plu IS NULL OR plu = '')")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '7')")
    conn.commit()

def migrate_v8(conn):
    """Add po_pdf_path setting for PO PDF export folder."""
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value, description) "
        "VALUES ('po_pdf_path', '', 'Folder path for exported PO PDFs')"
    )
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '8')")
    conn.commit()

def migrate_v9(conn):
    """Add separate email fields to suppliers table.
    Replaces the single 'email' catch-all with four specific addresses:
    email_orders, email_admin, email_accounts, email_rep.
    The original 'email' column is retained for backwards compatibility.
    """
    for col in ["email_orders", "email_admin", "email_accounts", "email_rep"]:
        try:
            conn.execute(f"ALTER TABLE suppliers ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass
    # Migrate existing email value into email_orders as a sensible default
    conn.execute("""
        UPDATE suppliers
        SET email_orders = email
        WHERE (email IS NOT NULL AND email != '')
          AND (email_orders IS NULL OR email_orders = '')
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '9')")
    conn.commit()
