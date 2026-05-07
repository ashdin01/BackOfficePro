import logging
import sqlite3
from database.connection import get_connection


def _add_column(conn, sql):
    """
    Execute an ALTER TABLE ... ADD COLUMN statement.
    Silently ignores 'duplicate column name' (column already exists — safe on
    re-run).  Any other OperationalError is re-raised so real failures are not
    masked.
    """
    try:
        conn.execute(sql)
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise


def apply_migrations():
    logging.info("apply_migrations() starting")
    conn = get_connection()
    try:
        version = conn.execute(
            "SELECT value FROM settings WHERE key='schema_version'"
        ).fetchone()
        current = int(version['value']) if version else 1
        logging.info(f"Current schema version: {current}")

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
        if current < 10:
            migrate_v10(conn)
            logging.info("Migration v10 applied: auto_reorder column on products")
        if current < 11:
            migrate_v11(conn)
            logging.info("Migration v11 applied: updated_at column on purchase_orders")
        if current < 12:
            migrate_v12(conn)
            logging.info("Migration v12 applied: is_promo column on po_lines")
        if current < 13:
            migrate_v13(conn)
            logging.info("Migration v13 applied: address column on suppliers")
        if current < 14:
            migrate_v14(conn)
            logging.info("Migration v14 applied: product_suppliers junction table")
        if current < 15:
            migrate_v15(conn)
            logging.info("Migration v15 applied: online_order fields on suppliers")
        if current < 16:
            migrate_v16(conn)
            logging.info("Migration v16 applied: per-supplier SKU, pack_qty, pack_unit")
        if current < 17:
            migrate_v17(conn)
            logging.info("Migration v17 applied: bundles and bundle_eligible tables")
        if current < 18:
            migrate_v18(conn)
            logging.info("Migration v18 applied: unit_qty on bundle_eligible")
        if current < 19:
            migrate_v19(conn)
            logging.info("Migration v19 applied: index on stock_movements(created_at)")
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
    _add_column(conn, "ALTER TABLE products ADD COLUMN brand TEXT DEFAULT ''")
    conn.execute("UPDATE settings SET value = '3' WHERE key = 'schema_version'")
    conn.commit()


def migrate_v4(conn):
    """Add sku and supplier_sku columns to products table."""
    _add_column(conn, "ALTER TABLE products ADD COLUMN sku TEXT DEFAULT ''")
    _add_column(conn, "ALTER TABLE products ADD COLUMN supplier_sku TEXT DEFAULT ''")
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
        _add_column(conn, f"ALTER TABLE suppliers ADD COLUMN {col} {typedef}")
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
    _add_column(conn, "ALTER TABLE products ADD COLUMN group_id INTEGER REFERENCES product_groups(id)")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '6')")
    conn.commit()


def migrate_v7(conn):
    """Add pack_qty, pack_unit, reorder_max, base_sku to products; actual_cost to po_lines;
    create plu_barcode_map and sales_daily tables."""
    for col, typedef in [
        ("pack_qty",    "INTEGER DEFAULT 1"),
        ("pack_unit",   "TEXT DEFAULT 'EA'"),
        ("reorder_max", "REAL DEFAULT 0"),
        ("base_sku",    "TEXT"),
    ]:
        _add_column(conn, f"ALTER TABLE products ADD COLUMN {col} {typedef}")
    _add_column(conn, "ALTER TABLE po_lines ADD COLUMN actual_cost REAL DEFAULT 0")
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
    Replaces the single 'email' catch-all with four specific addresses.
    The original 'email' column is retained for backwards compatibility.
    """
    for col in ["email_orders", "email_admin", "email_accounts", "email_rep"]:
        _add_column(conn, f"ALTER TABLE suppliers ADD COLUMN {col} TEXT DEFAULT ''")
    conn.execute("""
        UPDATE suppliers
        SET email_orders = email
        WHERE (email IS NOT NULL AND email != '')
          AND (email_orders IS NULL OR email_orders = '')
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '9')")
    conn.commit()


def migrate_v10(conn):
    """Add auto_reorder flag to products table."""
    _add_column(conn, "ALTER TABLE products ADD COLUMN auto_reorder INTEGER DEFAULT 0")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '10')")
    conn.commit()


def migrate_v11(conn):
    """Add updated_at column to purchase_orders table."""
    _add_column(conn, "ALTER TABLE purchase_orders ADD COLUMN updated_at DATETIME")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '11')")
    conn.commit()


def migrate_v12(conn):
    """Add is_promo column to po_lines table."""
    _add_column(conn, "ALTER TABLE po_lines ADD COLUMN is_promo INTEGER NOT NULL DEFAULT 0")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '12')")
    conn.commit()


def migrate_v13(conn):
    """Add address column to suppliers table."""
    _add_column(conn, "ALTER TABLE suppliers ADD COLUMN address TEXT")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '13')")
    conn.commit()


def migrate_v14(conn):
    """Create product_suppliers junction table; seed existing supplier_id as default."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_suppliers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode     TEXT    NOT NULL REFERENCES products(barcode),
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
            is_default  INTEGER NOT NULL DEFAULT 0,
            UNIQUE(barcode, supplier_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_suppliers_barcode  ON product_suppliers(barcode)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_suppliers_supplier ON product_suppliers(supplier_id)"
    )
    conn.execute("""
        INSERT OR IGNORE INTO product_suppliers (barcode, supplier_id, is_default)
        SELECT barcode, supplier_id, 1
        FROM products
        WHERE supplier_id IS NOT NULL
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '14')")
    conn.commit()


def migrate_v15(conn):
    """Add online ordering portal flag and note to suppliers table."""
    _add_column(conn, "ALTER TABLE suppliers ADD COLUMN online_order INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "ALTER TABLE suppliers ADD COLUMN online_order_note TEXT DEFAULT ''")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '15')")
    conn.commit()


def migrate_v16(conn):
    """Add per-supplier SKU, pack_qty, pack_unit to product_suppliers.
    Seeds values from the products table for each product's default supplier link."""
    _add_column(conn, "ALTER TABLE product_suppliers ADD COLUMN supplier_sku TEXT DEFAULT ''")
    _add_column(conn, "ALTER TABLE product_suppliers ADD COLUMN pack_qty INTEGER DEFAULT 1")
    _add_column(conn, "ALTER TABLE product_suppliers ADD COLUMN pack_unit TEXT DEFAULT 'EA'")
    conn.execute("""
        UPDATE product_suppliers
        SET supplier_sku = COALESCE((
                SELECT p.supplier_sku FROM products p WHERE p.barcode = product_suppliers.barcode
            ), ''),
            pack_qty = COALESCE((
                SELECT p.pack_qty FROM products p WHERE p.barcode = product_suppliers.barcode
            ), 1),
            pack_unit = COALESCE((
                SELECT p.pack_unit FROM products p WHERE p.barcode = product_suppliers.barcode
            ), 'EA')
        WHERE is_default = 1
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '16')")
    conn.commit()


def migrate_v18(conn):
    """Add unit_qty to bundle_eligible for unit-aware bundle pricing."""
    _add_column(conn, "ALTER TABLE bundle_eligible ADD COLUMN unit_qty INTEGER DEFAULT 1")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '18')")
    conn.commit()


def migrate_v19(conn):
    """Add index on stock_movements(created_at) for date-range history queries."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movements_created ON stock_movements(created_at DESC)")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '19')")
    conn.commit()


def migrate_v17(conn):
    """Add bundles and bundle_eligible tables for mixed-case selling."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bundles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            description  TEXT    DEFAULT '',
            required_qty INTEGER NOT NULL DEFAULT 4,
            price        REAL    NOT NULL DEFAULT 0,
            active       INTEGER NOT NULL DEFAULT 1,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bundle_eligible (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_id   INTEGER NOT NULL REFERENCES bundles(id),
            barcode     TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            UNIQUE(bundle_id, barcode)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bundle_eligible_bundle  ON bundle_eligible(bundle_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bundle_eligible_barcode ON bundle_eligible(barcode)")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '17')")
    conn.commit()
