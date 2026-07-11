import hashlib
import inspect
import logging
import marshal
import re
import sqlite3
import sys

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


def _fn_checksum(fn) -> str:
    """SHA-256 fingerprint of a migration function.

    Development (source available): hashes whitespace-normalised source so
    reformatting alone does not trigger a mismatch.

    PyInstaller / frozen builds (source unavailable): hashes the marshalled
    code object, which includes all SQL string constants and bytecode.
    """
    try:
        src = inspect.getsource(fn)
        normalised = re.sub(r'\s+', ' ', src).strip()
        return hashlib.sha256(normalised.encode()).hexdigest()
    except OSError:
        return hashlib.sha256(marshal.dumps(fn.__code__)).hexdigest()


def _ensure_migration_log(conn):
    """Create migration_log table if it doesn't exist (idempotent)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_log (
            version     INTEGER PRIMARY KEY,
            applied_at  TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            checksum    TEXT    NOT NULL DEFAULT ''
        )
    """)
    conn.commit()


def _ensure_db_meta(conn):
    """Create db_meta and seed it from settings.schema_version if needed.

    db_meta is the canonical version store from v54 onwards.  On the first
    run after upgrading an existing database, the table is created and seeded
    from the old settings row so that apply_migrations() picks up the correct
    starting version without re-running anything.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS db_meta (
            version INTEGER NOT NULL DEFAULT 1
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM db_meta").fetchone()[0] == 0:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='schema_version'"
        ).fetchone()
        seed = int(row['value']) if row else 1
        conn.execute("INSERT INTO db_meta (version) VALUES (?)", (seed,))
    conn.commit()


def _log_migration(conn, version: int, description: str, fn):
    """Record a freshly-applied migration in migration_log."""
    conn.execute("""
        INSERT OR IGNORE INTO migration_log (version, applied_at, description, checksum)
        VALUES (?, datetime('now', 'localtime'), ?, ?)
    """, (version, description, _fn_checksum(fn)))
    conn.commit()


def _check_integrity(conn):
    """Verify migration log integrity against _MIGRATIONS.

    Two checks:
    - Gap: every version in _MIGRATIONS at or below schema_version must have a
      log entry.  A missing entry means a migration was skipped or the log was
      corrupted.  Logged at WARNING only — gaps are expected on pre-log installs
      that haven't been backfilled yet.
    - Drift: for each logged version, recompute the checksum from the current
      function source and compare.  A mismatch means a migration function was
      edited after it was applied — schema and code may diverge.
      Raises RuntimeError to block startup if any drift is detected.
    """
    version_row = conn.execute("SELECT version FROM db_meta").fetchone()
    if not version_row:
        return
    current = int(version_row['version'])

    logged = {
        r['version']: r['checksum']
        for r in conn.execute("SELECT version, checksum FROM migration_log").fetchall()
    }

    # Gap check — warn only
    expected = {v for v in _MIGRATIONS if v <= current}
    for v in sorted(expected - logged.keys()):
        logging.warning(
            f"Migration log gap: v{v} has no log entry (schema_version={current}). "
            "The migration may have been skipped or the log was manually altered."
        )

    # Drift check — block startup on any mismatch.
    # Skipped in frozen (PyInstaller) builds: the bundle is immutable so
    # migration source cannot change between runs, and bytecode-based checksums
    # would not match source-based checksums stored by a prior dev-mode run.
    if getattr(sys, 'frozen', False):
        return

    drifted = []
    for v, stored in logged.items():
        entry = _MIGRATIONS.get(v)
        if entry is None:
            continue
        fn, _ = entry
        live = _fn_checksum(fn)
        if live != stored:
            logging.critical(
                f"Migration v{v} source has changed since it was applied "
                f"(stored={stored[:12]}… current={live[:12]}…). "
                "Schema and code may be out of sync."
            )
            drifted.append(v)

    if drifted:
        raise RuntimeError(
            f"Migration source drift detected for version(s): {sorted(drifted)}. "
            "A migration function was edited after being applied — the database schema "
            "and application code may be out of sync. "
            "Restore from backup or manually inspect the database before starting."
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def apply_migrations():
    logging.info("apply_migrations() starting")
    conn = get_connection()
    try:
        _ensure_migration_log(conn)
        _ensure_db_meta(conn)

        version_row = conn.execute("SELECT version FROM db_meta").fetchone()
        current = int(version_row['version']) if version_row else 1
        logging.info(f"Current schema version: {current}")

        for v in sorted(_MIGRATIONS):
            fn, description = _MIGRATIONS[v]
            if current < v:
                fn(conn)   # commits internally; may also update settings.schema_version
                # Update db_meta atomically with the migration_log entry so the
                # canonical version and the audit record are never out of step.
                conn.execute("UPDATE db_meta SET version=?", (v,))
                _log_migration(conn, v, description, fn)   # commits
                logging.info(f"Migration v{v} applied: {description}")

        # Backfill log entries for migrations applied before logging was introduced.
        # INSERT OR IGNORE means already-logged versions are untouched.
        for v, (fn, description) in _MIGRATIONS.items():
            if v <= current:
                conn.execute("""
                    INSERT OR IGNORE INTO migration_log
                        (version, applied_at, description, checksum)
                    VALUES (?, 'pre-log', ?, ?)
                """, (v, description, _fn_checksum(fn)))
        conn.commit()

        _check_integrity(conn)
        logging.info("apply_migrations() complete")
    except Exception as e:
        logging.critical(f"Migration failed: {e}", exc_info=True)
        raise
    finally:
        conn.release()


# ── Migration functions ───────────────────────────────────────────────────────

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


def migrate_v20(conn):
    """Add index on sales_daily(plu, sale_date) for per-PLU sales range queries."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_daily_plu_date ON sales_daily(plu, sale_date)")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '20')")
    conn.commit()


def migrate_v21(conn):
    """Add pack_qty to po_lines so reversals use the value recorded at order time."""
    conn.execute("ALTER TABLE po_lines ADD COLUMN pack_qty INTEGER NOT NULL DEFAULT 1")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '21')")
    conn.commit()


def migrate_v22(conn):
    """Add po_type to purchase_orders to support Credit/Return and Invoice Only orders."""
    conn.execute("ALTER TABLE purchase_orders ADD COLUMN po_type TEXT NOT NULL DEFAULT 'PO'")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '22')")
    conn.commit()


def migrate_v23(conn):
    """Add order_days to suppliers for home-screen order prompts."""
    _add_column(conn, "ALTER TABLE suppliers ADD COLUMN order_days TEXT DEFAULT ''")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '23')")
    conn.commit()


def migrate_v24(conn):
    """Add first-Monday and fortnightly order schedule fields to suppliers."""
    _add_column(conn, "ALTER TABLE suppliers ADD COLUMN order_first_monday INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "ALTER TABLE suppliers ADD COLUMN order_fortnightly_start TEXT DEFAULT ''")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '24')")
    conn.commit()


def migrate_v25(conn):
    """Add delivery_days to suppliers for milk demand forecasting."""
    _add_column(conn, "ALTER TABLE suppliers ADD COLUMN delivery_days TEXT DEFAULT ''")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '25')")
    conn.commit()


def migrate_v26(conn):
    """Add customers table for accounts receivable."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            code                TEXT NOT NULL UNIQUE,
            name                TEXT NOT NULL,
            abn                 TEXT DEFAULT '',
            address_line1       TEXT DEFAULT '',
            address_line2       TEXT DEFAULT '',
            suburb              TEXT DEFAULT '',
            state               TEXT DEFAULT '',
            postcode            TEXT DEFAULT '',
            email               TEXT DEFAULT '',
            phone               TEXT DEFAULT '',
            contact_name        TEXT DEFAULT '',
            payment_terms_days  INTEGER NOT NULL DEFAULT 37,
            credit_limit        REAL DEFAULT 0,
            active              INTEGER NOT NULL DEFAULT 1,
            notes               TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            updated_at          TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '26')")
    conn.commit()


def migrate_v27(conn):
    """Add AR invoices, lines, payments, credit notes tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ar_invoices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number  TEXT NOT NULL UNIQUE,
            customer_id     INTEGER NOT NULL,
            invoice_date    TEXT NOT NULL,
            due_date        TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'DRAFT',
            subtotal        REAL NOT NULL DEFAULT 0,
            gst_amount      REAL NOT NULL DEFAULT 0,
            total           REAL NOT NULL DEFAULT 0,
            amount_paid     REAL NOT NULL DEFAULT 0,
            notes           TEXT DEFAULT '',
            created_by      TEXT DEFAULT '',
            exported_to_myob INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS ar_invoice_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            barcode         TEXT DEFAULT '',
            description     TEXT NOT NULL,
            quantity        REAL NOT NULL DEFAULT 1,
            unit_price      REAL NOT NULL DEFAULT 0,
            discount_pct    REAL NOT NULL DEFAULT 0,
            gst_rate        REAL NOT NULL DEFAULT 10,
            line_subtotal   REAL NOT NULL DEFAULT 0,
            line_gst        REAL NOT NULL DEFAULT 0,
            line_total      REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id)
        );

        CREATE TABLE IF NOT EXISTS ar_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            customer_id     INTEGER NOT NULL,
            payment_date    TEXT NOT NULL,
            amount          REAL NOT NULL,
            method          TEXT NOT NULL DEFAULT 'EFT',
            reference       TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS ar_credit_notes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_note_number  TEXT NOT NULL UNIQUE,
            customer_id         INTEGER NOT NULL,
            invoice_id          INTEGER DEFAULT NULL,
            date                TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'DRAFT',
            subtotal            REAL NOT NULL DEFAULT 0,
            gst_amount          REAL NOT NULL DEFAULT 0,
            total               REAL NOT NULL DEFAULT 0,
            reason              TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ar_invoices_customer ON ar_invoices(customer_id);
        CREATE INDEX IF NOT EXISTS idx_ar_invoices_status   ON ar_invoices(status);
        CREATE INDEX IF NOT EXISTS idx_ar_invoice_lines_inv ON ar_invoice_lines(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_ar_payments_invoice  ON ar_payments(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_cust ON ar_credit_notes(customer_id);
    """)
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ar_next_invoice_number', '1')")
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ar_next_credit_number', '1')")
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ar_invoice_pdf_path', '')")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '27')")
    conn.commit()


def migrate_v28(conn):
    """Add bank reconciliation tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bank_csv_profiles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            delimiter       TEXT NOT NULL DEFAULT ',',
            has_header      INTEGER NOT NULL DEFAULT 1,
            skip_rows       INTEGER NOT NULL DEFAULT 0,
            amount_type     TEXT NOT NULL DEFAULT 'signed',
            col_date        INTEGER,
            col_amount      INTEGER,
            col_debit       INTEGER,
            col_credit      INTEGER,
            col_description INTEGER,
            col_reference   INTEGER,
            col_balance     INTEGER,
            date_format     TEXT NOT NULL DEFAULT '%d/%m/%Y',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS bank_transactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id      INTEGER NOT NULL REFERENCES bank_csv_profiles(id),
            import_batch    TEXT NOT NULL,
            txn_date        TEXT NOT NULL,
            amount          REAL NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            reference       TEXT DEFAULT '',
            balance         REAL,
            status          TEXT NOT NULL DEFAULT 'UNMATCHED',
            invoice_id      INTEGER REFERENCES ar_invoices(id),
            payment_id      INTEGER REFERENCES ar_payments(id),
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_bank_txn_batch  ON bank_transactions(import_batch);
        CREATE INDEX IF NOT EXISTS idx_bank_txn_status ON bank_transactions(status);
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '28')")
    conn.commit()


def migrate_v29(conn):
    """Add supplier_invoice_number to purchase_orders."""
    conn.execute(
        "ALTER TABLE purchase_orders ADD COLUMN supplier_invoice_number TEXT DEFAULT ''"
    )
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '29')")
    conn.commit()


def migrate_v30(conn):
    """Add po_charges table for freight/surcharges saved at receipt."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS po_charges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL REFERENCES purchase_orders(id),
            description     TEXT NOT NULL DEFAULT '',
            tax_rate        REAL NOT NULL DEFAULT 0,
            amount_inc_tax  REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_po_charges_po ON po_charges(po_id);
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '30')")
    conn.commit()


def migrate_v31(conn):
    """Add sort_order and is_note to po_lines."""
    conn.execute("ALTER TABLE po_lines ADD COLUMN is_note INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE po_lines ADD COLUMN sort_order INTEGER")
    conn.execute("UPDATE po_lines SET sort_order = id WHERE sort_order IS NULL")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '31')")
    conn.commit()


def migrate_v32(conn):
    """Add bank details columns to suppliers."""
    conn.execute("ALTER TABLE suppliers ADD COLUMN bank_account_name TEXT DEFAULT ''")
    conn.execute("ALTER TABLE suppliers ADD COLUMN bank_bsb TEXT DEFAULT ''")
    conn.execute("ALTER TABLE suppliers ADD COLUMN bank_account_number TEXT DEFAULT ''")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '32')")
    conn.commit()


def migrate_v33(conn):
    """Add source column to stock_movements to record whether change came from UI or API."""
    _add_column(conn, "ALTER TABLE stock_movements ADD COLUMN source TEXT DEFAULT ''")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '33')")
    conn.commit()


def migrate_v34(conn):
    """Add pos_sales ledger table for POS sale idempotency.

    Each POS transaction reference is written here before any SOH or movement
    rows are inserted.  A duplicate reference hits the PRIMARY KEY constraint
    and the whole sale is skipped, so a POS terminal that retries on a network
    timeout cannot double-decrement stock or double-count sales.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pos_sales (
            reference   TEXT    PRIMARY KEY,
            sale_date   TEXT    NOT NULL,
            operator    TEXT    NOT NULL DEFAULT '',
            received_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '34')")
    conn.commit()


def migrate_v35(conn):
    """Add indexes on sales_daily(sale_date) and customers(name).

    v20 added a composite (plu, sale_date) index which does not serve
    date-range queries that filter on sale_date alone.  customers(name) is used
    in ORDER BY and LIKE searches across all AR list views.
    """
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_daily_date ON sales_daily(sale_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_name    ON customers(name)")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '35')")
    conn.commit()


def migrate_v36(conn):
    """Create audit_log table for field-level change history on master data."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entity      TEXT NOT NULL,
            entity_key  TEXT NOT NULL,
            field       TEXT NOT NULL,
            old_value   TEXT,
            new_value   TEXT,
            changed_by  TEXT NOT NULL DEFAULT '',
            changed_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON audit_log(changed_at DESC)"
    )
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '36')")
    conn.commit()


def migrate_v37(conn):
    """Add ON DELETE CASCADE to child-table FK constraints.

    SQLite cannot alter existing FK constraints, so each affected table is
    recreated using the rename-create-copy-drop pattern with FK enforcement
    disabled for the duration.

    Tables changed (child data has no meaning without parent):
      po_lines.po_id, po_charges.po_id, ar_invoice_lines.invoice_id,
      stocktake_counts.session_id, bundle_eligible.bundle_id,
      product_suppliers (both FKs), stock_on_hand.barcode,
      barcode_aliases.master_barcode, product_selling_units.master_barcode.
    """
    # product_selling_units was present in schema.py from the start but was
    # never created by a migration.  Databases initialised from a schema that
    # predates the table will not have it, causing the RENAME below to fail.
    # Create it empty here so the rename-create-copy-drop pattern can proceed
    # (the INSERT will simply copy zero rows from the empty backup table).
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if 'product_selling_units' not in tables:
        conn.execute("""
            CREATE TABLE product_selling_units (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                master_barcode TEXT    NOT NULL,
                barcode        TEXT    UNIQUE,
                plu            TEXT,
                label          TEXT    NOT NULL DEFAULT '',
                unit_qty       REAL    NOT NULL DEFAULT 1,
                sell_price     REAL    NOT NULL DEFAULT 0,
                active         INTEGER NOT NULL DEFAULT 1,
                created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        BEGIN TRANSACTION;

        ALTER TABLE po_lines RENAME TO po_lines_old;
        CREATE TABLE po_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL,
            barcode         TEXT    NOT NULL,
            description     TEXT    NOT NULL,
            ordered_qty     REAL    NOT NULL,
            received_qty    REAL    NOT NULL DEFAULT 0,
            pack_qty        INTEGER NOT NULL DEFAULT 1,
            unit_cost       REAL    NOT NULL DEFAULT 0,
            notes           TEXT,
            actual_cost     REAL    DEFAULT 0,
            is_promo        INTEGER NOT NULL DEFAULT 0,
            is_note         INTEGER NOT NULL DEFAULT 0,
            sort_order      INTEGER,
            FOREIGN KEY (po_id)   REFERENCES purchase_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode) REFERENCES products(barcode)
        );
        INSERT INTO po_lines
            SELECT id, po_id, barcode, description, ordered_qty, received_qty,
                   pack_qty, unit_cost, notes, actual_cost, is_promo, is_note, sort_order
            FROM po_lines_old;
        DROP TABLE po_lines_old;

        ALTER TABLE po_charges RENAME TO po_charges_old;
        CREATE TABLE po_charges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            tax_rate        REAL NOT NULL DEFAULT 0,
            amount_inc_tax  REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE
        );
        INSERT INTO po_charges
            SELECT id, po_id, description, tax_rate, amount_inc_tax
            FROM po_charges_old;
        DROP TABLE po_charges_old;

        ALTER TABLE ar_invoice_lines RENAME TO ar_invoice_lines_old;
        CREATE TABLE ar_invoice_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            barcode         TEXT DEFAULT '',
            description     TEXT NOT NULL,
            quantity        REAL NOT NULL DEFAULT 1,
            unit_price      REAL NOT NULL DEFAULT 0,
            discount_pct    REAL NOT NULL DEFAULT 0,
            gst_rate        REAL NOT NULL DEFAULT 10,
            line_subtotal   REAL NOT NULL DEFAULT 0,
            line_gst        REAL NOT NULL DEFAULT 0,
            line_total      REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id) ON DELETE CASCADE
        );
        INSERT INTO ar_invoice_lines
            SELECT id, invoice_id, barcode, description, quantity, unit_price,
                   discount_pct, gst_rate, line_subtotal, line_gst, line_total
            FROM ar_invoice_lines_old;
        DROP TABLE ar_invoice_lines_old;

        ALTER TABLE stocktake_counts RENAME TO stocktake_counts_old;
        CREATE TABLE stocktake_counts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL,
            barcode         TEXT    NOT NULL,
            counted_qty     REAL    NOT NULL DEFAULT 0,
            scanned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES stocktake_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode)    REFERENCES products(barcode)
        );
        INSERT INTO stocktake_counts
            SELECT id, session_id, barcode, counted_qty, scanned_at
            FROM stocktake_counts_old;
        DROP TABLE stocktake_counts_old;

        ALTER TABLE bundle_eligible RENAME TO bundle_eligible_old;
        CREATE TABLE bundle_eligible (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_id   INTEGER NOT NULL,
            barcode     TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            unit_qty    INTEGER DEFAULT 1,
            FOREIGN KEY (bundle_id) REFERENCES bundles(id) ON DELETE CASCADE,
            UNIQUE(bundle_id, barcode)
        );
        INSERT INTO bundle_eligible
            SELECT id, bundle_id, barcode, description, unit_qty
            FROM bundle_eligible_old;
        DROP TABLE bundle_eligible_old;

        ALTER TABLE product_suppliers RENAME TO product_suppliers_old;
        CREATE TABLE product_suppliers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode      TEXT    NOT NULL,
            supplier_id  INTEGER NOT NULL,
            is_default   INTEGER NOT NULL DEFAULT 0,
            supplier_sku TEXT    DEFAULT '',
            pack_qty     INTEGER DEFAULT 1,
            pack_unit    TEXT    DEFAULT 'EA',
            FOREIGN KEY (barcode)     REFERENCES products(barcode) ON DELETE CASCADE,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)     ON DELETE CASCADE,
            UNIQUE(barcode, supplier_id)
        );
        INSERT INTO product_suppliers
            SELECT id, barcode, supplier_id, is_default, supplier_sku, pack_qty, pack_unit
            FROM product_suppliers_old;
        DROP TABLE product_suppliers_old;

        ALTER TABLE stock_on_hand RENAME TO stock_on_hand_old;
        CREATE TABLE stock_on_hand (
            barcode         TEXT    PRIMARY KEY,
            quantity        REAL    NOT NULL DEFAULT 0,
            last_updated    DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (barcode) REFERENCES products(barcode) ON DELETE CASCADE
        );
        INSERT INTO stock_on_hand
            SELECT barcode, quantity, last_updated
            FROM stock_on_hand_old;
        DROP TABLE stock_on_hand_old;

        ALTER TABLE barcode_aliases RENAME TO barcode_aliases_old;
        CREATE TABLE barcode_aliases (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            alias_barcode  TEXT    NOT NULL UNIQUE,
            master_barcode TEXT    NOT NULL,
            description    TEXT,
            created_at     TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (master_barcode) REFERENCES products(barcode) ON DELETE CASCADE
        );
        INSERT INTO barcode_aliases
            SELECT id, alias_barcode, master_barcode, description, created_at
            FROM barcode_aliases_old;
        DROP TABLE barcode_aliases_old;

        ALTER TABLE product_selling_units RENAME TO product_selling_units_old;
        CREATE TABLE product_selling_units (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            master_barcode TEXT    NOT NULL,
            barcode        TEXT    UNIQUE,
            plu            TEXT,
            label          TEXT    NOT NULL,
            unit_qty       REAL    NOT NULL DEFAULT 1,
            sell_price     REAL    NOT NULL DEFAULT 0,
            active         INTEGER NOT NULL DEFAULT 1,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_barcode) REFERENCES products(barcode) ON DELETE CASCADE
        );
        INSERT INTO product_selling_units
            SELECT id, master_barcode, barcode, plu, label, unit_qty, sell_price, active, created_at
            FROM product_selling_units_old;
        DROP TABLE product_selling_units_old;

        CREATE INDEX IF NOT EXISTS idx_po_lines_po_id           ON po_lines(po_id);
        CREATE INDEX IF NOT EXISTS idx_po_lines_barcode         ON po_lines(barcode);
        CREATE INDEX IF NOT EXISTS idx_po_charges_po            ON po_charges(po_id);
        CREATE INDEX IF NOT EXISTS idx_ar_invoice_lines_inv     ON ar_invoice_lines(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_session ON stocktake_counts(session_id);
        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_barcode ON stocktake_counts(barcode);
        CREATE INDEX IF NOT EXISTS idx_bundle_eligible_bundle   ON bundle_eligible(bundle_id);
        CREATE INDEX IF NOT EXISTS idx_bundle_eligible_barcode  ON bundle_eligible(barcode);
        CREATE INDEX IF NOT EXISTS idx_product_suppliers_barcode  ON product_suppliers(barcode);
        CREATE INDEX IF NOT EXISTS idx_product_suppliers_supplier ON product_suppliers(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_selling_units_master     ON product_selling_units(master_barcode);
        CREATE INDEX IF NOT EXISTS idx_selling_units_barcode    ON product_selling_units(barcode);

        COMMIT;
        PRAGMA foreign_keys = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '37')")
    conn.commit()


def migrate_v38(conn):
    """Add UNIQUE(session_id, barcode) to stocktake_counts.

    The application-level upsert previously used SELECT-then-INSERT, which
    has a race window when two devices scan the same barcode simultaneously.
    The UNIQUE constraint enables a single atomic INSERT ... ON CONFLICT DO UPDATE.
    Any pre-existing duplicate rows are merged by summing counted_qty.
    """
    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        BEGIN TRANSACTION;

        ALTER TABLE stocktake_counts RENAME TO stocktake_counts_old;
        CREATE TABLE stocktake_counts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL,
            barcode         TEXT    NOT NULL,
            counted_qty     REAL    NOT NULL DEFAULT 0,
            scanned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES stocktake_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode)    REFERENCES products(barcode),
            UNIQUE(session_id, barcode)
        );
        INSERT INTO stocktake_counts (session_id, barcode, counted_qty, scanned_at)
            SELECT session_id, barcode, SUM(counted_qty), MAX(scanned_at)
            FROM stocktake_counts_old
            GROUP BY session_id, barcode;
        DROP TABLE stocktake_counts_old;

        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_session ON stocktake_counts(session_id);
        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_barcode ON stocktake_counts(barcode);

        COMMIT;
        PRAGMA foreign_keys = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '38')")
    conn.commit()


def migrate_v39(conn):
    """Add ON DELETE RESTRICT / SET NULL to the remaining FK constraints.

    v37 added CASCADE to pure child tables.  This migration covers the
    business-logic relationships:

      RESTRICT (prevent deletion of referenced parent):
        product_groups.department_id, products.department_id,
        purchase_orders.supplier_id, po_lines.barcode,
        ar_payments.invoice_id + customer_id,
        ar_credit_notes.customer_id,
        bank_transactions.profile_id

      SET NULL (child survives, FK column cleared):
        products.supplier_id, products.group_id,
        stocktake_sessions.department_id,
        ar_credit_notes.invoice_id,
        bank_transactions.invoice_id + payment_id
    """
    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        BEGIN TRANSACTION;

        -- ── product_groups ────────────────────────────────────────────────────
        ALTER TABLE product_groups RENAME TO product_groups_old;
        CREATE TABLE product_groups (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            code          TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
            UNIQUE(department_id, code)
        );
        INSERT INTO product_groups
            SELECT id, department_id, code, name, active
            FROM product_groups_old;
        DROP TABLE product_groups_old;

        -- ── products ──────────────────────────────────────────────────────────
        ALTER TABLE products RENAME TO products_old;
        CREATE TABLE products (
            barcode         TEXT    PRIMARY KEY,
            base_sku        TEXT,
            plu             TEXT,
            description     TEXT    NOT NULL,
            department_id   INTEGER NOT NULL,
            supplier_id     INTEGER,
            unit            TEXT    DEFAULT 'EA',
            sell_price      REAL    DEFAULT 0,
            cost_price      REAL    DEFAULT 0,
            tax_rate        REAL    DEFAULT 0,
            reorder_point   REAL    DEFAULT 0,
            reorder_qty     REAL    DEFAULT 0,
            reorder_max     REAL    DEFAULT 0,
            pack_qty        INTEGER DEFAULT 1,
            pack_unit       TEXT    DEFAULT 'EA',
            variable_weight INTEGER NOT NULL DEFAULT 0,
            expected        INTEGER NOT NULL DEFAULT 1,
            active          INTEGER NOT NULL DEFAULT 1,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            brand           TEXT    DEFAULT '',
            sku             TEXT    DEFAULT '',
            supplier_sku    TEXT    DEFAULT '',
            group_id        INTEGER,
            auto_reorder    INTEGER DEFAULT 0,
            FOREIGN KEY (department_id) REFERENCES departments(id)       ON DELETE RESTRICT,
            FOREIGN KEY (supplier_id)   REFERENCES suppliers(id)         ON DELETE SET NULL,
            FOREIGN KEY (group_id)      REFERENCES product_groups(id)    ON DELETE SET NULL
        );
        INSERT INTO products
            SELECT barcode, base_sku, plu, description, department_id, supplier_id,
                   unit, sell_price, cost_price, tax_rate, reorder_point, reorder_qty,
                   reorder_max, pack_qty, pack_unit, variable_weight, expected, active,
                   created_at, updated_at, brand, sku, supplier_sku, group_id, auto_reorder
            FROM products_old;
        DROP TABLE products_old;

        CREATE INDEX IF NOT EXISTS idx_products_department ON products(department_id);
        CREATE INDEX IF NOT EXISTS idx_products_supplier   ON products(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_products_base_sku   ON products(base_sku);

        -- ── purchase_orders ───────────────────────────────────────────────────
        ALTER TABLE purchase_orders RENAME TO purchase_orders_old;
        CREATE TABLE purchase_orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number       TEXT    NOT NULL UNIQUE,
            supplier_id     INTEGER NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'DRAFT',
            po_type         TEXT    NOT NULL DEFAULT 'PO',
            delivery_date   DATE,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            sent_at         DATETIME,
            received_at     DATETIME,
            created_by      TEXT,
            updated_at      DATETIME,
            supplier_invoice_number TEXT DEFAULT '',
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
        );
        INSERT INTO purchase_orders
            SELECT id, po_number, supplier_id, status, po_type, delivery_date,
                   notes, created_at, sent_at, received_at, created_by, updated_at,
                   supplier_invoice_number
            FROM purchase_orders_old;
        DROP TABLE purchase_orders_old;

        CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_po_status   ON purchase_orders(status);

        -- ── po_lines — add RESTRICT to barcode (CASCADE on po_id kept) ────────
        ALTER TABLE po_lines RENAME TO po_lines_old;
        CREATE TABLE po_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL,
            barcode         TEXT    NOT NULL,
            description     TEXT    NOT NULL,
            ordered_qty     REAL    NOT NULL,
            received_qty    REAL    NOT NULL DEFAULT 0,
            pack_qty        INTEGER NOT NULL DEFAULT 1,
            unit_cost       REAL    NOT NULL DEFAULT 0,
            notes           TEXT,
            actual_cost     REAL    DEFAULT 0,
            is_promo        INTEGER NOT NULL DEFAULT 0,
            is_note         INTEGER NOT NULL DEFAULT 0,
            sort_order      INTEGER,
            FOREIGN KEY (po_id)   REFERENCES purchase_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode) REFERENCES products(barcode)   ON DELETE RESTRICT
        );
        INSERT INTO po_lines
            SELECT id, po_id, barcode, description, ordered_qty, received_qty,
                   pack_qty, unit_cost, notes, actual_cost, is_promo, is_note, sort_order
            FROM po_lines_old;
        DROP TABLE po_lines_old;

        CREATE INDEX IF NOT EXISTS idx_po_lines_po_id   ON po_lines(po_id);
        CREATE INDEX IF NOT EXISTS idx_po_lines_barcode ON po_lines(barcode);

        -- ── stocktake_sessions ────────────────────────────────────────────────
        ALTER TABLE stocktake_sessions RENAME TO stocktake_sessions_old;
        CREATE TABLE stocktake_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            label           TEXT    NOT NULL,
            department_id   INTEGER,
            status          TEXT    NOT NULL DEFAULT 'OPEN',
            started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            closed_at       DATETIME,
            created_by      TEXT,
            notes           TEXT,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
        );
        INSERT INTO stocktake_sessions
            SELECT id, label, department_id, status, started_at, closed_at,
                   created_by, notes
            FROM stocktake_sessions_old;
        DROP TABLE stocktake_sessions_old;

        -- ── ar_payments ───────────────────────────────────────────────────────
        ALTER TABLE ar_payments RENAME TO ar_payments_old;
        CREATE TABLE ar_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            customer_id     INTEGER NOT NULL,
            payment_date    TEXT NOT NULL,
            amount          REAL NOT NULL,
            method          TEXT NOT NULL DEFAULT 'EFT',
            reference       TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id)  ON DELETE RESTRICT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)    ON DELETE RESTRICT
        );
        INSERT INTO ar_payments
            SELECT id, invoice_id, customer_id, payment_date, amount,
                   method, reference, notes, created_at
            FROM ar_payments_old;
        DROP TABLE ar_payments_old;

        CREATE INDEX IF NOT EXISTS idx_ar_payments_invoice ON ar_payments(invoice_id);

        -- ── ar_credit_notes ───────────────────────────────────────────────────
        ALTER TABLE ar_credit_notes RENAME TO ar_credit_notes_old;
        CREATE TABLE ar_credit_notes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_note_number  TEXT NOT NULL UNIQUE,
            customer_id         INTEGER NOT NULL,
            invoice_id          INTEGER DEFAULT NULL,
            date                TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'DRAFT',
            subtotal            REAL NOT NULL DEFAULT 0,
            gst_amount          REAL NOT NULL DEFAULT 0,
            total               REAL NOT NULL DEFAULT 0,
            reason              TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)    ON DELETE RESTRICT,
            FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id)  ON DELETE SET NULL
        );
        INSERT INTO ar_credit_notes
            SELECT id, credit_note_number, customer_id, invoice_id, date,
                   status, subtotal, gst_amount, total, reason, created_at
            FROM ar_credit_notes_old;
        DROP TABLE ar_credit_notes_old;

        CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_cust ON ar_credit_notes(customer_id);

        -- ── bank_transactions ─────────────────────────────────────────────────
        ALTER TABLE bank_transactions RENAME TO bank_transactions_old;
        CREATE TABLE bank_transactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id      INTEGER NOT NULL,
            import_batch    TEXT NOT NULL,
            txn_date        TEXT NOT NULL,
            amount          REAL NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            reference       TEXT DEFAULT '',
            balance         REAL,
            status          TEXT NOT NULL DEFAULT 'UNMATCHED',
            invoice_id      INTEGER,
            payment_id      INTEGER,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (profile_id) REFERENCES bank_csv_profiles(id) ON DELETE RESTRICT,
            FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id)       ON DELETE SET NULL,
            FOREIGN KEY (payment_id) REFERENCES ar_payments(id)       ON DELETE SET NULL
        );
        INSERT INTO bank_transactions
            SELECT id, profile_id, import_batch, txn_date, amount,
                   description, reference, balance, status, invoice_id,
                   payment_id, created_at
            FROM bank_transactions_old;
        DROP TABLE bank_transactions_old;

        CREATE INDEX IF NOT EXISTS idx_bank_txn_batch  ON bank_transactions(import_batch);
        CREATE INDEX IF NOT EXISTS idx_bank_txn_status ON bank_transactions(status);

        COMMIT;
        PRAGMA foreign_keys = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '39')")
    conn.commit()


def migrate_v40(conn):
    """Add CHECK constraints on bounded numeric and boolean columns.

    Affected tables (recreated via rename-create-copy-drop):
      products      — tax_rate [0,100], prices/reorder >= 0, active IN (0,1)
      ar_invoice_lines — discount_pct/gst_rate [0,100], quantity/unit_price >= 0
      po_charges    — tax_rate [0,100], amount_inc_tax >= 0
      departments, suppliers, customers, product_groups, bundles,
      product_selling_units — active IN (0,1)

    PRAGMA legacy_alter_table = ON is required so that renaming a parent table
    (suppliers, departments, etc.) does not cause SQLite 3.26+ to auto-rewrite
    the FK clauses in child tables to point at the *_old intermediates.
    """
    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        -- ── products ──────────────────────────────────────────────────────────
        ALTER TABLE products RENAME TO products_old;
        CREATE TABLE products (
            barcode         TEXT    PRIMARY KEY,
            base_sku        TEXT,
            plu             TEXT,
            description     TEXT    NOT NULL,
            department_id   INTEGER NOT NULL,
            supplier_id     INTEGER,
            unit            TEXT    DEFAULT 'EA',
            sell_price      REAL    DEFAULT 0    CHECK (sell_price   >= 0),
            cost_price      REAL    DEFAULT 0    CHECK (cost_price   >= 0),
            tax_rate        REAL    DEFAULT 0    CHECK (tax_rate  BETWEEN 0 AND 100),
            reorder_point   REAL    DEFAULT 0    CHECK (reorder_point >= 0),
            reorder_qty     REAL    DEFAULT 0    CHECK (reorder_qty   >= 0),
            reorder_max     REAL    DEFAULT 0    CHECK (reorder_max   >= 0),
            pack_qty        INTEGER DEFAULT 1    CHECK (pack_qty > 0),
            pack_unit       TEXT    DEFAULT 'EA',
            variable_weight INTEGER NOT NULL DEFAULT 0 CHECK (variable_weight IN (0,1)),
            expected        INTEGER NOT NULL DEFAULT 1 CHECK (expected        IN (0,1)),
            active          INTEGER NOT NULL DEFAULT 1 CHECK (active          IN (0,1)),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            brand           TEXT    DEFAULT '',
            sku             TEXT    DEFAULT '',
            supplier_sku    TEXT    DEFAULT '',
            group_id        INTEGER,
            auto_reorder    INTEGER DEFAULT 0    CHECK (auto_reorder IN (0,1)),
            FOREIGN KEY (department_id) REFERENCES departments(id)    ON DELETE RESTRICT,
            FOREIGN KEY (supplier_id)   REFERENCES suppliers(id)      ON DELETE SET NULL,
            FOREIGN KEY (group_id)      REFERENCES product_groups(id) ON DELETE SET NULL
        );
        INSERT INTO products
            SELECT barcode, base_sku, plu, description, department_id, supplier_id,
                   unit, sell_price, cost_price, tax_rate, reorder_point, reorder_qty,
                   reorder_max, pack_qty, pack_unit, variable_weight, expected, active,
                   created_at, updated_at, brand, sku, supplier_sku, group_id, auto_reorder
            FROM products_old;
        DROP TABLE products_old;

        CREATE INDEX IF NOT EXISTS idx_products_department ON products(department_id);
        CREATE INDEX IF NOT EXISTS idx_products_supplier   ON products(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_products_base_sku   ON products(base_sku);

        -- ── ar_invoice_lines ──────────────────────────────────────────────────
        ALTER TABLE ar_invoice_lines RENAME TO ar_invoice_lines_old;
        CREATE TABLE ar_invoice_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            barcode         TEXT DEFAULT '',
            description     TEXT NOT NULL,
            quantity        REAL NOT NULL DEFAULT 1  CHECK (quantity    > 0),
            unit_price      REAL NOT NULL DEFAULT 0  CHECK (unit_price  >= 0),
            discount_pct    REAL NOT NULL DEFAULT 0  CHECK (discount_pct BETWEEN 0 AND 100),
            gst_rate        REAL NOT NULL DEFAULT 10 CHECK (gst_rate     BETWEEN 0 AND 100),
            line_subtotal   REAL NOT NULL DEFAULT 0,
            line_gst        REAL NOT NULL DEFAULT 0,
            line_total      REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id) ON DELETE CASCADE
        );
        INSERT INTO ar_invoice_lines
            SELECT id, invoice_id, barcode, description, quantity, unit_price,
                   discount_pct, gst_rate, line_subtotal, line_gst, line_total
            FROM ar_invoice_lines_old;
        DROP TABLE ar_invoice_lines_old;

        CREATE INDEX IF NOT EXISTS idx_ar_invoice_lines_inv ON ar_invoice_lines(invoice_id);

        -- ── po_charges ────────────────────────────────────────────────────────
        ALTER TABLE po_charges RENAME TO po_charges_old;
        CREATE TABLE po_charges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            tax_rate        REAL NOT NULL DEFAULT 0 CHECK (tax_rate BETWEEN 0 AND 100),
            amount_inc_tax  REAL NOT NULL DEFAULT 0 CHECK (amount_inc_tax >= 0),
            FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE
        );
        INSERT INTO po_charges
            SELECT id, po_id, description, tax_rate, MAX(amount_inc_tax, 0)
            FROM po_charges_old;
        DROP TABLE po_charges_old;

        CREATE INDEX IF NOT EXISTS idx_po_charges_po ON po_charges(po_id);

        -- ── departments ───────────────────────────────────────────────────────
        ALTER TABLE departments RENAME TO departments_old;
        CREATE TABLE departments (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            code   TEXT    NOT NULL UNIQUE,
            name   TEXT    NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
        );
        INSERT INTO departments SELECT id, code, name, active FROM departments_old;
        DROP TABLE departments_old;

        -- ── suppliers ─────────────────────────────────────────────────────────
        ALTER TABLE suppliers RENAME TO suppliers_old;
        CREATE TABLE suppliers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            code            TEXT    NOT NULL UNIQUE,
            name            TEXT    NOT NULL,
            contact_name    TEXT,
            phone           TEXT,
            email           TEXT,
            address         TEXT,
            account_number  TEXT,
            payment_terms   TEXT,
            notes           TEXT,
            active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            abn             TEXT    DEFAULT '',
            rep_name        TEXT    DEFAULT '',
            rep_phone       TEXT    DEFAULT '',
            order_minimum   REAL    DEFAULT 0   CHECK (order_minimum >= 0),
            email_orders        TEXT    DEFAULT '',
            email_admin         TEXT    DEFAULT '',
            email_accounts      TEXT    DEFAULT '',
            email_rep           TEXT    DEFAULT '',
            online_order        INTEGER NOT NULL DEFAULT 0 CHECK (online_order        IN (0,1)),
            online_order_note   TEXT    DEFAULT '',
            order_days              TEXT    DEFAULT '',
            order_first_monday      INTEGER NOT NULL DEFAULT 0 CHECK (order_first_monday IN (0,1)),
            order_fortnightly_start TEXT    DEFAULT '',
            delivery_days           TEXT    DEFAULT '',
            bank_account_name       TEXT    DEFAULT '',
            bank_bsb                TEXT    DEFAULT '',
            bank_account_number     TEXT    DEFAULT ''
        );
        INSERT INTO suppliers
            SELECT id, code, name, contact_name, phone, email, address,
                   account_number, payment_terms, notes, active, created_at,
                   abn, rep_name, rep_phone, order_minimum,
                   email_orders, email_admin, email_accounts, email_rep,
                   online_order, online_order_note, order_days,
                   order_first_monday, order_fortnightly_start, delivery_days,
                   bank_account_name, bank_bsb, bank_account_number
            FROM suppliers_old;
        DROP TABLE suppliers_old;

        -- ── customers ─────────────────────────────────────────────────────────
        ALTER TABLE customers RENAME TO customers_old;
        CREATE TABLE customers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            code                TEXT NOT NULL UNIQUE,
            name                TEXT NOT NULL,
            abn                 TEXT DEFAULT '',
            address_line1       TEXT DEFAULT '',
            address_line2       TEXT DEFAULT '',
            suburb              TEXT DEFAULT '',
            state               TEXT DEFAULT '',
            postcode            TEXT DEFAULT '',
            email               TEXT DEFAULT '',
            phone               TEXT DEFAULT '',
            contact_name        TEXT DEFAULT '',
            payment_terms_days  INTEGER NOT NULL DEFAULT 37 CHECK (payment_terms_days >= 0),
            credit_limit        REAL DEFAULT 0              CHECK (credit_limit       >= 0),
            active              INTEGER NOT NULL DEFAULT 1  CHECK (active IN (0,1)),
            notes               TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            updated_at          TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO customers
            SELECT id, code, name, abn, address_line1, address_line2,
                   suburb, state, postcode, email, phone, contact_name,
                   payment_terms_days, credit_limit, active, notes,
                   created_at, updated_at
            FROM customers_old;
        DROP TABLE customers_old;

        CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);

        -- ── product_groups ────────────────────────────────────────────────────
        ALTER TABLE product_groups RENAME TO product_groups_old;
        CREATE TABLE product_groups (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            code          TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
            UNIQUE(department_id, code)
        );
        INSERT INTO product_groups
            SELECT id, department_id, code, name, active FROM product_groups_old;
        DROP TABLE product_groups_old;

        -- ── bundles ───────────────────────────────────────────────────────────
        ALTER TABLE bundles RENAME TO bundles_old;
        CREATE TABLE bundles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            description  TEXT    DEFAULT '',
            required_qty INTEGER NOT NULL DEFAULT 4 CHECK (required_qty > 0),
            price        REAL    NOT NULL DEFAULT 0 CHECK (price >= 0),
            active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO bundles
            SELECT id, name, description, required_qty, price, active, created_at
            FROM bundles_old;
        DROP TABLE bundles_old;

        -- ── product_selling_units ─────────────────────────────────────────────
        ALTER TABLE product_selling_units RENAME TO product_selling_units_old;
        CREATE TABLE product_selling_units (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            master_barcode TEXT    NOT NULL,
            barcode        TEXT    UNIQUE,
            plu            TEXT,
            label          TEXT    NOT NULL,
            unit_qty       REAL    NOT NULL DEFAULT 1 CHECK (unit_qty   > 0),
            sell_price     REAL    NOT NULL DEFAULT 0 CHECK (sell_price >= 0),
            active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_barcode) REFERENCES products(barcode) ON DELETE CASCADE
        );
        INSERT INTO product_selling_units
            SELECT id, master_barcode, barcode, plu, label,
                   unit_qty, sell_price, active, created_at
            FROM product_selling_units_old;
        DROP TABLE product_selling_units_old;

        CREATE INDEX IF NOT EXISTS idx_selling_units_master  ON product_selling_units(master_barcode);
        CREATE INDEX IF NOT EXISTS idx_selling_units_barcode ON product_selling_units(barcode);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '40')")
    conn.commit()


def migrate_v41(conn):
    """Add indexes on three unindexed FK columns used in WHERE / JOIN clauses."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ar_payments_customer"
        " ON ar_payments(customer_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_invoice"
        " ON ar_credit_notes(invoice_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bank_txn_profile"
        " ON bank_transactions(profile_id)"
    )
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '41')")
    conn.commit()


def migrate_v42(conn):
    """No-op — the FK-cascade bug this migration originally fixed is now prevented
    by migrate_v40 itself (via PRAGMA legacy_alter_table = ON).

    Existing databases that ran the original v42 are already correct.
    Fresh installs running the corrected v40 never need this migration.
    migrate_v53 updates the stored checksum in migration_log to reflect
    these corrected function bodies.
    """
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '42')")
    conn.commit()


def _migrate_v42_original(conn):  # pragma: no cover — never called, historical reference
    """Original v42 body that rebuilt all FK-affected tables. Now superseded by the
    PRAGMA legacy_alter_table = ON fix in migrate_v40. Kept so git history is not
    the only place to find this SQL."""
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        -- ── products ──────────────────────────────────────────────────────────
        ALTER TABLE products RENAME TO products_tmp;
        CREATE TABLE products (
            barcode         TEXT    PRIMARY KEY,
            base_sku        TEXT,
            plu             TEXT,
            description     TEXT    NOT NULL,
            department_id   INTEGER NOT NULL,
            supplier_id     INTEGER,
            unit            TEXT    DEFAULT 'EA',
            sell_price      REAL    DEFAULT 0    CHECK (sell_price   >= 0),
            cost_price      REAL    DEFAULT 0    CHECK (cost_price   >= 0),
            tax_rate        REAL    DEFAULT 0    CHECK (tax_rate  BETWEEN 0 AND 100),
            reorder_point   REAL    DEFAULT 0    CHECK (reorder_point >= 0),
            reorder_qty     REAL    DEFAULT 0    CHECK (reorder_qty   >= 0),
            reorder_max     REAL    DEFAULT 0    CHECK (reorder_max   >= 0),
            pack_qty        INTEGER DEFAULT 1    CHECK (pack_qty > 0),
            pack_unit       TEXT    DEFAULT 'EA',
            variable_weight INTEGER NOT NULL DEFAULT 0 CHECK (variable_weight IN (0,1)),
            expected        INTEGER NOT NULL DEFAULT 1 CHECK (expected        IN (0,1)),
            active          INTEGER NOT NULL DEFAULT 1 CHECK (active          IN (0,1)),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            brand           TEXT    DEFAULT '',
            sku             TEXT    DEFAULT '',
            supplier_sku    TEXT    DEFAULT '',
            group_id        INTEGER,
            auto_reorder    INTEGER DEFAULT 0    CHECK (auto_reorder IN (0,1)),
            FOREIGN KEY (department_id) REFERENCES departments(id)    ON DELETE RESTRICT,
            FOREIGN KEY (supplier_id)   REFERENCES suppliers(id)      ON DELETE SET NULL,
            FOREIGN KEY (group_id)      REFERENCES product_groups(id) ON DELETE SET NULL
        );
        INSERT INTO products
            SELECT barcode, base_sku, plu, description, department_id, supplier_id,
                   unit, sell_price, cost_price, tax_rate, reorder_point, reorder_qty,
                   reorder_max, pack_qty, pack_unit, variable_weight, expected, active,
                   created_at, updated_at, brand, sku, supplier_sku, group_id, auto_reorder
            FROM products_tmp;
        DROP TABLE products_tmp;

        CREATE INDEX IF NOT EXISTS idx_products_department ON products(department_id);
        CREATE INDEX IF NOT EXISTS idx_products_supplier   ON products(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_products_base_sku   ON products(base_sku);

        -- ── purchase_orders ───────────────────────────────────────────────────
        ALTER TABLE purchase_orders RENAME TO purchase_orders_tmp;
        CREATE TABLE purchase_orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number       TEXT    NOT NULL UNIQUE,
            supplier_id     INTEGER NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'DRAFT',
            po_type         TEXT    NOT NULL DEFAULT 'PO',
            delivery_date   DATE,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            sent_at         DATETIME,
            received_at     DATETIME,
            created_by      TEXT,
            updated_at      DATETIME,
            supplier_invoice_number TEXT DEFAULT '',
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
        );
        INSERT INTO purchase_orders
            SELECT id, po_number, supplier_id, status, po_type, delivery_date, notes,
                   created_at, sent_at, received_at, created_by, updated_at,
                   supplier_invoice_number
            FROM purchase_orders_tmp;
        DROP TABLE purchase_orders_tmp;

        CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_po_status   ON purchase_orders(status);

        -- ── stocktake_sessions ────────────────────────────────────────────────
        ALTER TABLE stocktake_sessions RENAME TO stocktake_sessions_tmp;
        CREATE TABLE stocktake_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            label           TEXT    NOT NULL,
            department_id   INTEGER,
            status          TEXT    NOT NULL DEFAULT 'OPEN',
            started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            closed_at       DATETIME,
            created_by      TEXT,
            notes           TEXT,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
        );
        INSERT INTO stocktake_sessions
            SELECT id, label, department_id, status, started_at, closed_at,
                   created_by, notes
            FROM stocktake_sessions_tmp;
        DROP TABLE stocktake_sessions_tmp;

        -- ── ar_invoices ───────────────────────────────────────────────────────
        ALTER TABLE ar_invoices RENAME TO ar_invoices_tmp;
        CREATE TABLE ar_invoices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number  TEXT NOT NULL UNIQUE,
            customer_id     INTEGER NOT NULL,
            invoice_date    TEXT NOT NULL,
            due_date        TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'DRAFT',
            subtotal        REAL NOT NULL DEFAULT 0,
            gst_amount      REAL NOT NULL DEFAULT 0,
            total           REAL NOT NULL DEFAULT 0,
            amount_paid     REAL NOT NULL DEFAULT 0,
            notes           TEXT DEFAULT '',
            created_by      TEXT DEFAULT '',
            exported_to_myob INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
        );
        INSERT INTO ar_invoices
            SELECT id, invoice_number, customer_id, invoice_date, due_date, status,
                   subtotal, gst_amount, total, amount_paid, notes, created_by,
                   exported_to_myob, created_at, updated_at
            FROM ar_invoices_tmp;
        DROP TABLE ar_invoices_tmp;

        CREATE INDEX IF NOT EXISTS idx_ar_invoices_customer ON ar_invoices(customer_id);
        CREATE INDEX IF NOT EXISTS idx_ar_invoices_status   ON ar_invoices(status);

        -- ── po_lines ──────────────────────────────────────────────────────────
        ALTER TABLE po_lines RENAME TO po_lines_tmp;
        CREATE TABLE po_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL,
            barcode         TEXT    NOT NULL,
            description     TEXT    NOT NULL,
            ordered_qty     REAL    NOT NULL,
            received_qty    REAL    NOT NULL DEFAULT 0,
            pack_qty        INTEGER NOT NULL DEFAULT 1,
            unit_cost       REAL    NOT NULL DEFAULT 0,
            notes           TEXT,
            actual_cost     REAL    DEFAULT 0,
            is_promo        INTEGER NOT NULL DEFAULT 0,
            is_note         INTEGER NOT NULL DEFAULT 0,
            sort_order      INTEGER,
            FOREIGN KEY (po_id)   REFERENCES purchase_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode) REFERENCES products(barcode)   ON DELETE RESTRICT
        );
        INSERT INTO po_lines
            SELECT id, po_id, barcode, description, ordered_qty, received_qty,
                   pack_qty, unit_cost, notes, actual_cost, is_promo, is_note, sort_order
            FROM po_lines_tmp;
        DROP TABLE po_lines_tmp;

        CREATE INDEX IF NOT EXISTS idx_po_lines_po_id   ON po_lines(po_id);
        CREATE INDEX IF NOT EXISTS idx_po_lines_barcode ON po_lines(barcode);

        -- ── stock_movements ───────────────────────────────────────────────────
        ALTER TABLE stock_movements RENAME TO stock_movements_tmp;
        CREATE TABLE stock_movements (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode         TEXT    NOT NULL,
            movement_type   TEXT    NOT NULL,
            quantity        REAL    NOT NULL,
            reference       TEXT,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by      TEXT,
            source          TEXT    DEFAULT '',
            FOREIGN KEY (barcode) REFERENCES products(barcode)
        );
        INSERT INTO stock_movements
            SELECT id, barcode, movement_type, quantity, reference, notes,
                   created_at, created_by, source
            FROM stock_movements_tmp;
        DROP TABLE stock_movements_tmp;

        CREATE INDEX IF NOT EXISTS idx_movements_barcode ON stock_movements(barcode);
        CREATE INDEX IF NOT EXISTS idx_movements_type    ON stock_movements(movement_type);
        CREATE INDEX IF NOT EXISTS idx_movements_created ON stock_movements(created_at DESC);

        -- ── stock_on_hand ─────────────────────────────────────────────────────
        ALTER TABLE stock_on_hand RENAME TO stock_on_hand_tmp;
        CREATE TABLE stock_on_hand (
            barcode         TEXT    PRIMARY KEY,
            quantity        REAL    NOT NULL DEFAULT 0,
            last_updated    DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (barcode) REFERENCES products(barcode) ON DELETE CASCADE
        );
        INSERT INTO stock_on_hand
            SELECT barcode, quantity, last_updated
            FROM stock_on_hand_tmp;
        DROP TABLE stock_on_hand_tmp;

        -- ── barcode_aliases ───────────────────────────────────────────────────
        ALTER TABLE barcode_aliases RENAME TO barcode_aliases_tmp;
        CREATE TABLE barcode_aliases (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            alias_barcode  TEXT    NOT NULL UNIQUE,
            master_barcode TEXT    NOT NULL,
            description    TEXT,
            created_at     TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (master_barcode) REFERENCES products(barcode) ON DELETE CASCADE
        );
        INSERT INTO barcode_aliases
            SELECT id, alias_barcode, master_barcode, description, created_at
            FROM barcode_aliases_tmp;
        DROP TABLE barcode_aliases_tmp;

        -- ── stocktake_counts ──────────────────────────────────────────────────
        ALTER TABLE stocktake_counts RENAME TO stocktake_counts_tmp;
        CREATE TABLE stocktake_counts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL,
            barcode         TEXT    NOT NULL,
            counted_qty     REAL    NOT NULL DEFAULT 0,
            scanned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES stocktake_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode)    REFERENCES products(barcode),
            UNIQUE(session_id, barcode)
        );
        INSERT INTO stocktake_counts
            SELECT id, session_id, barcode, counted_qty, scanned_at
            FROM stocktake_counts_tmp;
        DROP TABLE stocktake_counts_tmp;

        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_session ON stocktake_counts(session_id);
        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_barcode ON stocktake_counts(barcode);

        -- ── product_suppliers ─────────────────────────────────────────────────
        ALTER TABLE product_suppliers RENAME TO product_suppliers_tmp;
        CREATE TABLE product_suppliers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode      TEXT    NOT NULL,
            supplier_id  INTEGER NOT NULL,
            is_default   INTEGER NOT NULL DEFAULT 0,
            supplier_sku TEXT    DEFAULT '',
            pack_qty     INTEGER DEFAULT 1,
            pack_unit    TEXT    DEFAULT 'EA',
            FOREIGN KEY (barcode)     REFERENCES products(barcode)  ON DELETE CASCADE,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)      ON DELETE CASCADE,
            UNIQUE(barcode, supplier_id)
        );
        INSERT INTO product_suppliers
            SELECT id, barcode, supplier_id, is_default, supplier_sku, pack_qty, pack_unit
            FROM product_suppliers_tmp;
        DROP TABLE product_suppliers_tmp;

        CREATE INDEX IF NOT EXISTS idx_product_suppliers_barcode  ON product_suppliers(barcode);
        CREATE INDEX IF NOT EXISTS idx_product_suppliers_supplier ON product_suppliers(supplier_id);

        -- ── ar_payments ───────────────────────────────────────────────────────
        ALTER TABLE ar_payments RENAME TO ar_payments_tmp;
        CREATE TABLE ar_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            customer_id     INTEGER NOT NULL,
            payment_date    TEXT NOT NULL,
            amount          REAL NOT NULL,
            method          TEXT NOT NULL DEFAULT 'EFT',
            reference       TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id)  ON DELETE RESTRICT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)    ON DELETE RESTRICT
        );
        INSERT INTO ar_payments
            SELECT id, invoice_id, customer_id, payment_date, amount,
                   method, reference, notes, created_at
            FROM ar_payments_tmp;
        DROP TABLE ar_payments_tmp;

        CREATE INDEX IF NOT EXISTS idx_ar_payments_invoice  ON ar_payments(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_ar_payments_customer ON ar_payments(customer_id);

        -- ── ar_credit_notes ───────────────────────────────────────────────────
        ALTER TABLE ar_credit_notes RENAME TO ar_credit_notes_tmp;
        CREATE TABLE ar_credit_notes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_note_number  TEXT NOT NULL UNIQUE,
            customer_id         INTEGER NOT NULL,
            invoice_id          INTEGER DEFAULT NULL,
            date                TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'DRAFT',
            subtotal            REAL NOT NULL DEFAULT 0,
            gst_amount          REAL NOT NULL DEFAULT 0,
            total               REAL NOT NULL DEFAULT 0,
            reason              TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)    ON DELETE RESTRICT,
            FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id)  ON DELETE SET NULL
        );
        INSERT INTO ar_credit_notes
            SELECT id, credit_note_number, customer_id, invoice_id, date,
                   status, subtotal, gst_amount, total, reason, created_at
            FROM ar_credit_notes_tmp;
        DROP TABLE ar_credit_notes_tmp;

        CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_cust    ON ar_credit_notes(customer_id);
        CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_invoice ON ar_credit_notes(invoice_id);

        -- ── bundle_eligible ───────────────────────────────────────────────────
        ALTER TABLE bundle_eligible RENAME TO bundle_eligible_tmp;
        CREATE TABLE bundle_eligible (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_id   INTEGER NOT NULL,
            barcode     TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            unit_qty    INTEGER DEFAULT 1,
            FOREIGN KEY (bundle_id) REFERENCES bundles(id) ON DELETE CASCADE,
            UNIQUE(bundle_id, barcode)
        );
        INSERT INTO bundle_eligible
            SELECT id, bundle_id, barcode, description, unit_qty
            FROM bundle_eligible_tmp;
        DROP TABLE bundle_eligible_tmp;

        CREATE INDEX IF NOT EXISTS idx_bundle_eligible_bundle  ON bundle_eligible(bundle_id);
        CREATE INDEX IF NOT EXISTS idx_bundle_eligible_barcode ON bundle_eligible(barcode);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)


def migrate_v43(conn):
    """Add ON DELETE RESTRICT to stock_movements.barcode FK.

    Without a delete rule the FK was unenforced: deleting a product left
    orphaned movement rows with a dangling barcode reference, corrupting the
    audit trail.  RESTRICT is correct here — products are soft-deleted
    (active=0), so a hard-delete of a product that has movement history is
    always a mistake.
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        ALTER TABLE stock_movements RENAME TO stock_movements_tmp;
        CREATE TABLE stock_movements (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode         TEXT    NOT NULL,
            movement_type   TEXT    NOT NULL,
            quantity        REAL    NOT NULL,
            reference       TEXT,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by      TEXT,
            source          TEXT    DEFAULT '',
            FOREIGN KEY (barcode) REFERENCES products(barcode) ON DELETE RESTRICT
        );
        INSERT INTO stock_movements
            SELECT id, barcode, movement_type, quantity, reference, notes,
                   created_at, created_by, source
            FROM stock_movements_tmp;
        DROP TABLE stock_movements_tmp;

        CREATE INDEX IF NOT EXISTS idx_movements_barcode ON stock_movements(barcode);
        CREATE INDEX IF NOT EXISTS idx_movements_type    ON stock_movements(movement_type);
        CREATE INDEX IF NOT EXISTS idx_movements_created ON stock_movements(created_at DESC);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '43')")
    conn.commit()


def migrate_v44(conn):
    """Fix ar_invoice_lines.barcode: NULL-able + ON DELETE RESTRICT FK.

    barcode='' was used as a sentinel for description-only lines (freight,
    comments, etc.).  Empty string cannot have a FK because '' is not a valid
    products.barcode.  Switching to NULL lets SQLite skip FK checks for
    description-only lines while enforcing the reference for product lines.
    ON DELETE RESTRICT prevents hard-deleting a product that appears on a
    historical invoice.  Existing '' rows are converted to NULL.
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        ALTER TABLE ar_invoice_lines RENAME TO ar_invoice_lines_tmp;
        CREATE TABLE ar_invoice_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            barcode         TEXT    DEFAULT NULL,
            description     TEXT    NOT NULL,
            quantity        REAL    NOT NULL DEFAULT 1  CHECK (quantity    > 0),
            unit_price      REAL    NOT NULL DEFAULT 0  CHECK (unit_price  >= 0),
            discount_pct    REAL    NOT NULL DEFAULT 0  CHECK (discount_pct BETWEEN 0 AND 100),
            gst_rate        REAL    NOT NULL DEFAULT 10 CHECK (gst_rate     BETWEEN 0 AND 100),
            line_subtotal   REAL    NOT NULL DEFAULT 0,
            line_gst        REAL    NOT NULL DEFAULT 0,
            line_total      REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id)      ON DELETE CASCADE,
            FOREIGN KEY (barcode)    REFERENCES products(barcode)     ON DELETE RESTRICT
        );
        INSERT INTO ar_invoice_lines
            SELECT id, invoice_id,
                   NULLIF(barcode, ''),
                   description, quantity, unit_price,
                   discount_pct, gst_rate, line_subtotal, line_gst, line_total
            FROM ar_invoice_lines_tmp;
        DROP TABLE ar_invoice_lines_tmp;

        CREATE INDEX IF NOT EXISTS idx_ar_invoice_lines_inv ON ar_invoice_lines(invoice_id);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '44')")
    conn.commit()


def migrate_v45(conn):
    """Add ON DELETE CASCADE to stocktake_counts.barcode FK.

    Stocktake counts are operational session data, not audit history.  When a
    product is hard-deleted its counts in any open session lose meaning and
    should be removed automatically.  CASCADE is appropriate here (contrast
    stock_movements which uses RESTRICT because it is an audit trail).
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        ALTER TABLE stocktake_counts RENAME TO stocktake_counts_tmp;
        CREATE TABLE stocktake_counts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL,
            barcode         TEXT    NOT NULL,
            counted_qty     REAL    NOT NULL DEFAULT 0,
            scanned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES stocktake_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode)    REFERENCES products(barcode)       ON DELETE CASCADE,
            UNIQUE(session_id, barcode)
        );
        INSERT INTO stocktake_counts
            SELECT id, session_id, barcode, counted_qty, scanned_at
            FROM stocktake_counts_tmp;
        DROP TABLE stocktake_counts_tmp;

        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_session ON stocktake_counts(session_id);
        CREATE INDEX IF NOT EXISTS idx_stocktake_counts_barcode ON stocktake_counts(barcode);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '45')")
    conn.commit()


def migrate_v50(conn):
    """Add CHECK (barcode IS NULL OR barcode != '') to ar_invoice_lines.

    NULL means a description-only line (no FK check, by SQLite design).
    Non-NULL must be a non-empty string referencing products(barcode).
    This closes the gap where application code enforces the invariant but the
    schema itself would accept barcode='' and silently bypass the FK check.
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        ALTER TABLE ar_invoice_lines RENAME TO ar_invoice_lines_tmp;
        CREATE TABLE ar_invoice_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            barcode         TEXT    DEFAULT NULL
                                CHECK (barcode IS NULL OR barcode != ''),
            description     TEXT    NOT NULL,
            quantity        REAL    NOT NULL DEFAULT 1  CHECK (quantity    > 0),
            unit_price      REAL    NOT NULL DEFAULT 0  CHECK (unit_price  >= 0),
            discount_pct    REAL    NOT NULL DEFAULT 0  CHECK (discount_pct BETWEEN 0 AND 100),
            gst_rate        REAL    NOT NULL DEFAULT 10 CHECK (gst_rate     BETWEEN 0 AND 100),
            line_subtotal   REAL    NOT NULL DEFAULT 0,
            line_gst        REAL    NOT NULL DEFAULT 0,
            line_total      REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id)  ON DELETE CASCADE,
            FOREIGN KEY (barcode)    REFERENCES products(barcode) ON DELETE RESTRICT
        );
        INSERT INTO ar_invoice_lines
            SELECT id, invoice_id, NULLIF(barcode, ''), description,
                   quantity, unit_price, discount_pct, gst_rate,
                   line_subtotal, line_gst, line_total
            FROM ar_invoice_lines_tmp;
        DROP TABLE ar_invoice_lines_tmp;

        CREATE INDEX IF NOT EXISTS idx_ar_invoice_lines_inv ON ar_invoice_lines(invoice_id);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '50')")
    conn.commit()


def migrate_v51(conn):
    """Remove PRAGMA foreign_keys workaround from po_lines note-line inserts.

    po_lines.barcode was TEXT NOT NULL, forcing add_note() to disable FK
    enforcement via PRAGMA foreign_keys = OFF in order to insert '' as a
    sentinel for description-only lines.  This migration:
      - Makes barcode nullable (TEXT DEFAULT NULL)
      - Adds CHECK (barcode IS NULL OR barcode != '') to close the empty-string
        bypass that previously required the PRAGMA workaround
      - Converts existing '' sentinel values to NULL
    After this migration, add_note() inserts NULL and the PRAGMA is no longer
    needed.  SQLite FK checks are skipped for NULL by design.
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        ALTER TABLE po_lines RENAME TO po_lines_tmp;
        CREATE TABLE po_lines (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL,
            barcode         TEXT    DEFAULT NULL
                                CHECK (barcode IS NULL OR barcode != ''),
            description     TEXT    NOT NULL,
            ordered_qty     REAL    NOT NULL,
            received_qty    REAL    NOT NULL DEFAULT 0,
            pack_qty        INTEGER NOT NULL DEFAULT 1,
            unit_cost       REAL    NOT NULL DEFAULT 0,
            notes           TEXT,
            actual_cost     REAL    DEFAULT 0,
            is_promo        INTEGER NOT NULL DEFAULT 0,
            is_note         INTEGER NOT NULL DEFAULT 0,
            sort_order      INTEGER,
            FOREIGN KEY (po_id)   REFERENCES purchase_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (barcode) REFERENCES products(barcode)   ON DELETE RESTRICT
        );
        INSERT INTO po_lines
            SELECT id, po_id, NULLIF(barcode, ''), description,
                   ordered_qty, received_qty, pack_qty, unit_cost,
                   notes, actual_cost, is_promo, is_note, sort_order
            FROM po_lines_tmp;
        DROP TABLE po_lines_tmp;

        CREATE INDEX IF NOT EXISTS idx_po_lines_po_id   ON po_lines(po_id);
        CREATE INDEX IF NOT EXISTS idx_po_lines_barcode ON po_lines(barcode);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '51')")
    conn.commit()


def migrate_v52(conn):
    """Drop unused password_hash column from users.

    password_hash was never populated by the application; all authentication
    uses the pin column (now PBKDF2-SHA256).  The column is removed by the
    standard SQLite rename-create-copy-drop pattern.
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        ALTER TABLE users RENAME TO users_tmp;
        CREATE TABLE users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            full_name       TEXT,
            pin             TEXT,
            role            TEXT    NOT NULL DEFAULT 'STAFF'
                                CHECK (role IN ('ADMIN','MANAGER','STAFF')),
            active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO users
            SELECT id, username, full_name, pin, role, active, created_at
            FROM users_tmp;
        DROP TABLE users_tmp;

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '52')")
    conn.commit()


def migrate_v49(conn):
    """Add ON DELETE CASCADE FK on bundle_eligible.barcode → products(barcode).

    bundle_eligible rows whose barcode no longer exists in products are orphaned
    data (the product was hard-deleted before the FK existed).  They are removed
    before the FK is enforced so the recreate does not fail an FK check.
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        DELETE FROM bundle_eligible
        WHERE barcode NOT IN (SELECT barcode FROM products);

        ALTER TABLE bundle_eligible RENAME TO bundle_eligible_tmp;
        CREATE TABLE bundle_eligible (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_id   INTEGER NOT NULL,
            barcode     TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            unit_qty    INTEGER DEFAULT 1,
            FOREIGN KEY (bundle_id) REFERENCES bundles(id)       ON DELETE CASCADE,
            FOREIGN KEY (barcode)   REFERENCES products(barcode) ON DELETE CASCADE,
            UNIQUE(bundle_id, barcode)
        );
        INSERT INTO bundle_eligible
            SELECT id, bundle_id, barcode, description, unit_qty
            FROM bundle_eligible_tmp;
        DROP TABLE bundle_eligible_tmp;

        CREATE INDEX IF NOT EXISTS idx_bundle_eligible_bundle  ON bundle_eligible(bundle_id);
        CREATE INDEX IF NOT EXISTS idx_bundle_eligible_barcode ON bundle_eligible(barcode);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '49')")
    conn.commit()


def migrate_v48(conn):
    """Add CHECK constraints on status/role/active enum columns.

    Three tables recreated via rename-create-copy-drop:

      users
        role   IN ('ADMIN','MANAGER','STAFF')
        active IN (0,1)

      ar_credit_notes
        status IN ('DRAFT','SENT','APPLIED','VOID')

      bank_transactions
        status IN ('UNMATCHED','MATCHED','IGNORED')

    PRAGMA legacy_alter_table = ON prevents SQLite 3.26+ from rewriting FK
    clauses in tables that reference these three (none do, but it is kept as a
    safety net consistent with all prior recreate migrations).
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        -- ── users ─────────────────────────────────────────────────────────────
        ALTER TABLE users RENAME TO users_tmp;
        CREATE TABLE users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            full_name       TEXT,
            pin             TEXT,
            password_hash   TEXT,
            role            TEXT    NOT NULL DEFAULT 'STAFF'
                                CHECK (role IN ('ADMIN','MANAGER','STAFF')),
            active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO users
            SELECT id, username, full_name, pin, password_hash,
                   role, active, created_at
            FROM users_tmp;
        DROP TABLE users_tmp;

        -- ── ar_credit_notes ───────────────────────────────────────────────────
        ALTER TABLE ar_credit_notes RENAME TO ar_credit_notes_tmp;
        CREATE TABLE ar_credit_notes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_note_number  TEXT NOT NULL UNIQUE,
            customer_id         INTEGER NOT NULL,
            invoice_id          INTEGER DEFAULT NULL,
            date                TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'DRAFT'
                                    CHECK (status IN ('DRAFT','SENT','APPLIED','VOID')),
            subtotal            REAL NOT NULL DEFAULT 0,
            gst_amount          REAL NOT NULL DEFAULT 0,
            total               REAL NOT NULL DEFAULT 0,
            reason              TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)    ON DELETE RESTRICT,
            FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id)  ON DELETE SET NULL
        );
        INSERT INTO ar_credit_notes
            SELECT id, credit_note_number, customer_id, invoice_id, date,
                   status, subtotal, gst_amount, total, reason, created_at
            FROM ar_credit_notes_tmp;
        DROP TABLE ar_credit_notes_tmp;

        CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_cust    ON ar_credit_notes(customer_id);
        CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_invoice ON ar_credit_notes(invoice_id);

        -- ── bank_transactions ─────────────────────────────────────────────────
        ALTER TABLE bank_transactions RENAME TO bank_transactions_tmp;
        CREATE TABLE bank_transactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id      INTEGER NOT NULL,
            import_batch    TEXT NOT NULL,
            txn_date        TEXT NOT NULL,
            amount          REAL NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            reference       TEXT DEFAULT '',
            balance         REAL,
            status          TEXT NOT NULL DEFAULT 'UNMATCHED'
                                CHECK (status IN ('UNMATCHED','MATCHED','IGNORED')),
            invoice_id      INTEGER,
            payment_id      INTEGER,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (profile_id) REFERENCES bank_csv_profiles(id) ON DELETE RESTRICT,
            FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id)       ON DELETE SET NULL,
            FOREIGN KEY (payment_id) REFERENCES ar_payments(id)       ON DELETE SET NULL
        );
        INSERT INTO bank_transactions
            SELECT id, profile_id, import_batch, txn_date, amount,
                   description, reference, balance, status, invoice_id,
                   payment_id, created_at
            FROM bank_transactions_tmp;
        DROP TABLE bank_transactions_tmp;

        CREATE INDEX IF NOT EXISTS idx_bank_txn_batch   ON bank_transactions(import_batch);
        CREATE INDEX IF NOT EXISTS idx_bank_txn_status  ON bank_transactions(status);
        CREATE INDEX IF NOT EXISTS idx_bank_txn_profile ON bank_transactions(profile_id);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '48')")
    conn.commit()


def migrate_v47(conn):
    """Add CHECK constraints on status enum columns.

    Three tables are recreated (rename-create-copy-drop) because SQLite does
    not support ALTER TABLE ADD CONSTRAINT.  PRAGMA legacy_alter_table = ON
    prevents SQLite 3.26+ from rewriting FK clauses in sibling tables that
    reference purchase_orders and ar_invoices.

    Allowed values:
      purchase_orders.status  — DRAFT, SENT, PARTIAL, RECEIVED, CANCELLED,
                                REVERSED, CLOSED
      ar_invoices.status      — DRAFT, SENT, PARTIAL, PAID, VOID, OVERDUE
      stocktake_sessions.status — OPEN, CLOSED
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        -- ── purchase_orders ───────────────────────────────────────────────────
        ALTER TABLE purchase_orders RENAME TO purchase_orders_tmp;
        CREATE TABLE purchase_orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number       TEXT    NOT NULL UNIQUE,
            supplier_id     INTEGER NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'DRAFT'
                                CHECK (status IN ('DRAFT','SENT','PARTIAL',
                                                  'RECEIVED','CANCELLED',
                                                  'REVERSED','CLOSED')),
            po_type         TEXT    NOT NULL DEFAULT 'PO',
            delivery_date   DATE,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            sent_at         DATETIME,
            received_at     DATETIME,
            created_by      TEXT,
            updated_at      DATETIME,
            supplier_invoice_number TEXT DEFAULT '',
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
        );
        INSERT INTO purchase_orders
            SELECT id, po_number, supplier_id, status, po_type, delivery_date,
                   notes, created_at, sent_at, received_at, created_by,
                   updated_at, supplier_invoice_number
            FROM purchase_orders_tmp;
        DROP TABLE purchase_orders_tmp;

        CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_po_status   ON purchase_orders(status);

        -- ── ar_invoices ───────────────────────────────────────────────────────
        ALTER TABLE ar_invoices RENAME TO ar_invoices_tmp;
        CREATE TABLE ar_invoices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number  TEXT NOT NULL UNIQUE,
            customer_id     INTEGER NOT NULL,
            invoice_date    TEXT NOT NULL,
            due_date        TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'DRAFT'
                                CHECK (status IN ('DRAFT','SENT','PARTIAL',
                                                  'PAID','VOID','OVERDUE')),
            subtotal        REAL NOT NULL DEFAULT 0,
            gst_amount      REAL NOT NULL DEFAULT 0,
            total           REAL NOT NULL DEFAULT 0,
            amount_paid     REAL NOT NULL DEFAULT 0,
            notes           TEXT DEFAULT '',
            created_by      TEXT DEFAULT '',
            exported_to_myob INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
        );
        INSERT INTO ar_invoices
            SELECT id, invoice_number, customer_id, invoice_date, due_date,
                   status, subtotal, gst_amount, total, amount_paid, notes,
                   created_by, exported_to_myob, created_at, updated_at
            FROM ar_invoices_tmp;
        DROP TABLE ar_invoices_tmp;

        CREATE INDEX IF NOT EXISTS idx_ar_invoices_customer ON ar_invoices(customer_id);
        CREATE INDEX IF NOT EXISTS idx_ar_invoices_status   ON ar_invoices(status);

        -- ── stocktake_sessions ────────────────────────────────────────────────
        ALTER TABLE stocktake_sessions RENAME TO stocktake_sessions_tmp;
        CREATE TABLE stocktake_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            label           TEXT    NOT NULL,
            department_id   INTEGER,
            status          TEXT    NOT NULL DEFAULT 'OPEN'
                                CHECK (status IN ('OPEN','CLOSED')),
            started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            closed_at       DATETIME,
            created_by      TEXT,
            notes           TEXT,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
        );
        INSERT INTO stocktake_sessions
            SELECT id, label, department_id, status, started_at, closed_at,
                   created_by, notes
            FROM stocktake_sessions_tmp;
        DROP TABLE stocktake_sessions_tmp;

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys      = ON;
    """)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '47')")
    conn.commit()


def migrate_v46(conn):
    """Add payment_ref idempotency key to ar_payments.

    payment_ref is a UUID generated by the application at call time.  A UNIQUE
    index on this column prevents the same payment being inserted twice if the
    caller retries (e.g. rapid double-click or network retry in the REST path).
    Existing rows are backfilled with 'legacy-<id>' so the UNIQUE index can be
    created without conflicts.
    """
    conn.execute("ALTER TABLE ar_payments ADD COLUMN payment_ref TEXT")
    conn.execute(
        "UPDATE ar_payments SET payment_ref = 'legacy-' || CAST(id AS TEXT)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_ar_payments_payment_ref ON ar_payments(payment_ref)"
    )
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '46')")
    conn.commit()


def migrate_v53(conn):
    """Backfill corrected checksums for migrate_v40 and migrate_v42.

    migrate_v40 was fixed to include PRAGMA legacy_alter_table = ON so SQLite
    does not auto-rewrite FK clauses in child tables when a parent table is
    renamed.  migrate_v42, which existed solely to undo that damage, is now a
    no-op.  Both functions have different source than what was originally stored
    in migration_log, so this migration updates those checksums to match —
    preventing drift detection from blocking startup on existing installs.
    """
    conn.execute(
        "UPDATE migration_log SET checksum=? WHERE version=40",
        (_fn_checksum(migrate_v40),)
    )
    conn.execute(
        "UPDATE migration_log SET checksum=? WHERE version=42",
        (_fn_checksum(migrate_v42),)
    )
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '53')")
    conn.commit()


def migrate_v54(conn):
    """Move schema_version out of the shared settings table into db_meta.

    settings is general app config — a bulk DELETE FROM settings would
    destroy the version marker and replay every migration on next start.
    db_meta is owned exclusively by the migration system and is never
    cleared by application code.

    _ensure_db_meta() has already created db_meta and seeded it from
    settings before the migration loop runs, so this function only needs
    to remove the now-redundant settings row.
    apply_migrations() updates db_meta.version to 54 after this returns.
    """
    conn.execute("DELETE FROM settings WHERE key='schema_version'")
    conn.commit()


def migrate_v55(conn):
    """Add departments.no_negative_soh — clamp stock on hand at zero.

    Fresh produce is sold by PLU/weight and its counts drift, so a negative
    SOH is always noise rather than information. With the flag set on a
    department, any movement that would take one of its products below zero
    clamps the stored SOH to zero and records a compensating ADJUSTMENT_IN
    movement (see models.stock_on_hand.clamp_negative_soh). Enabled for
    FRESH by default.

    Also repairs db_meta housekeeping: the schema seeded it with INSERT OR
    IGNORE but the table has no unique constraint, so every startup appended
    a duplicate row. Collapse to a single row, and remove the stale
    settings.schema_version key that migrate_v54 would have deleted had the
    pre-stamped db_meta row not prevented it from running.
    """
    cols = {r['name'] for r in conn.execute("PRAGMA table_info(departments)").fetchall()}
    if 'no_negative_soh' not in cols:
        conn.execute("""
            ALTER TABLE departments ADD COLUMN no_negative_soh
                INTEGER NOT NULL DEFAULT 0 CHECK (no_negative_soh IN (0,1))
        """)
    # Runs once per database (fresh installs seed db_meta at 54), so this
    # default never overrides a later user choice to disable the flag.
    conn.execute("UPDATE departments SET no_negative_soh = 1 WHERE code = 'FRESH'")

    # Backfill: zero out SOH already negative in flagged departments, with a
    # compensating movement per product so movement history reconciles.
    conn.execute("""
        INSERT INTO stock_movements
            (barcode, movement_type, quantity, reference, notes, created_by, source)
        SELECT s.barcode, 'ADJUSTMENT_IN', -s.quantity, 'v55-migration',
               'Auto-clamp: department does not allow negative SOH', 'migration', ''
        FROM stock_on_hand s
        JOIN products p    ON p.barcode = s.barcode
        JOIN departments d ON d.id = p.department_id
        WHERE s.quantity < 0 AND d.no_negative_soh = 1
    """)
    conn.execute("""
        UPDATE stock_on_hand
           SET quantity = 0, last_updated = CURRENT_TIMESTAMP
         WHERE quantity < 0
           AND barcode IN (
               SELECT p.barcode FROM products p
               JOIN departments d ON d.id = p.department_id
               WHERE d.no_negative_soh = 1
           )
    """)
    conn.execute("DELETE FROM db_meta WHERE rowid NOT IN (SELECT MIN(rowid) FROM db_meta)")
    conn.execute("DELETE FROM settings WHERE key = 'schema_version'")
    conn.commit()


def migrate_v56(conn):
    """Add online_available flag to products for the shop.littleredapple.com.au storefront.

    Products with online_available = 1 are surfaced in the online shop.
    Staff tag lines manually via the product list in BackOfficePro.
    """
    _add_column(conn, """
        ALTER TABLE products ADD COLUMN online_available
            INTEGER NOT NULL DEFAULT 0 CHECK (online_available IN (0,1))
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_products_online ON products(online_available)")
    conn.commit()


# ── Migration registry ────────────────────────────────────────────────────────
# Maps version number → (function, description).
# Entries are applied in sorted version order by apply_migrations().
# Never remove or reorder entries; only append new ones.

def migrate_v57(conn):
    """Add online_notes text field to products for shop.littleredapple.com.au product pages."""
    _add_column(conn, "ALTER TABLE products ADD COLUMN online_notes TEXT")
    conn.commit()


def migrate_v58(conn):
    """Add received_weight column to po_lines.

    Variable-weight lines need the actual weight received (kg) persisted
    separately from received_qty (which stays an item/carton count) so
    line totals can be computed as weight × cost/kg after the fact.
    """
    _add_column(conn, """
        ALTER TABLE po_lines ADD COLUMN received_weight
            REAL NOT NULL DEFAULT 0
    """)
    conn.commit()


def migrate_v59(conn):
    """Add group_id to stocktake_sessions for sub-department stocktake filtering."""
    _add_column(conn, """
        ALTER TABLE stocktake_sessions ADD COLUMN group_id INTEGER
            REFERENCES product_groups(id) ON DELETE SET NULL
    """)
    conn.commit()


def migrate_v60(conn):
    """Add atria_import_log table to track daily ATRIA sales import attempts.

    Records every attempt, including zero-sale days (e.g. store closed), so
    the startup catch-up sync can tell "already checked, nothing to import"
    apart from "never attempted" and doesn't keep retrying closed days.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS atria_import_log (
            sale_date     TEXT    PRIMARY KEY,
            imported_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            row_count     INTEGER NOT NULL DEFAULT 0,
            status        TEXT    NOT NULL DEFAULT 'OK' CHECK (status IN ('OK', 'ERROR')),
            error_message TEXT
        )
    """)
    conn.commit()


def migrate_v61(conn):
    """Add unmatched_count to atria_import_log so an unresolved PLU (a sale
    that couldn't be matched to a product barcode, so stock was never
    decremented for it) is visible without someone first noticing a wrong
    stock-on-hand figure downstream."""
    _add_column(conn, """
        ALTER TABLE atria_import_log ADD COLUMN unmatched_count INTEGER NOT NULL DEFAULT 0
    """)
    conn.commit()


_MIGRATIONS: dict[int, tuple] = {
    2:  (migrate_v2,  "barcode_aliases"),
    3:  (migrate_v3,  "brand column"),
    4:  (migrate_v4,  "sku, supplier_sku columns"),
    5:  (migrate_v5,  "supplier abn, rep_name, rep_phone, order_minimum"),
    6:  (migrate_v6,  "product_groups table + group_id on products"),
    7:  (migrate_v7,  "sales_daily, plu_barcode_map"),
    8:  (migrate_v8,  "po_pdf_path setting"),
    9:  (migrate_v9,  "supplier email_orders, email_admin, email_accounts, email_rep"),
    10: (migrate_v10, "auto_reorder column on products"),
    11: (migrate_v11, "updated_at column on purchase_orders"),
    12: (migrate_v12, "is_promo column on po_lines"),
    13: (migrate_v13, "address column on suppliers"),
    14: (migrate_v14, "product_suppliers junction table"),
    15: (migrate_v15, "online_order fields on suppliers"),
    16: (migrate_v16, "per-supplier SKU, pack_qty, pack_unit"),
    17: (migrate_v17, "bundles and bundle_eligible tables"),
    18: (migrate_v18, "unit_qty on bundle_eligible"),
    19: (migrate_v19, "index on stock_movements(created_at)"),
    20: (migrate_v20, "index on sales_daily(plu, sale_date)"),
    21: (migrate_v21, "pack_qty column on po_lines"),
    22: (migrate_v22, "po_type column on purchase_orders"),
    23: (migrate_v23, "order_days column on suppliers"),
    24: (migrate_v24, "order_first_monday, order_fortnightly_start on suppliers"),
    25: (migrate_v25, "delivery_days on suppliers"),
    26: (migrate_v26, "customers table"),
    27: (migrate_v27, "ar_invoices, ar_invoice_lines, ar_payments, ar_credit_notes"),
    28: (migrate_v28, "bank_csv_profiles, bank_transactions"),
    29: (migrate_v29, "purchase_orders.supplier_invoice_number"),
    30: (migrate_v30, "po_charges table"),
    31: (migrate_v31, "po_lines sort_order + is_note"),
    32: (migrate_v32, "suppliers bank details columns"),
    33: (migrate_v33, "source column on stock_movements"),
    34: (migrate_v34, "pos_sales idempotency ledger"),
    35: (migrate_v35, "indexes on sales_daily(sale_date) and customers(name)"),
    36: (migrate_v36, "audit_log table for master data change history"),
    37: (migrate_v37, "ON DELETE CASCADE on child-table FK constraints"),
    38: (migrate_v38, "stocktake_counts UNIQUE(session_id, barcode) for atomic upsert"),
    39: (migrate_v39, "remaining ON DELETE RESTRICT/SET NULL on FK constraints"),
    40: (migrate_v40, "CHECK constraints on bounded numeric and boolean columns"),
    41: (migrate_v41, "indexes on ar_payments(customer_id), ar_credit_notes(invoice_id), bank_transactions(profile_id)"),
    42: (migrate_v42, "no-op — v40 now uses legacy_alter_table=ON, so no FK repair needed"),
    43: (migrate_v43, "ON DELETE RESTRICT on stock_movements.barcode FK"),
    44: (migrate_v44, "ar_invoice_lines.barcode NULL + ON DELETE RESTRICT FK to products"),
    45: (migrate_v45, "ON DELETE CASCADE on stocktake_counts.barcode FK"),
    46: (migrate_v46, "payment_ref idempotency key on ar_payments"),
    47: (migrate_v47, "CHECK constraints on purchase_orders, ar_invoices, stocktake_sessions status enums"),
    48: (migrate_v48, "CHECK constraints on users.role/active, ar_credit_notes.status, bank_transactions.status"),
    49: (migrate_v49, "ON DELETE CASCADE FK on bundle_eligible.barcode → products"),
    50: (migrate_v50, "CHECK (barcode IS NULL OR barcode != '') on ar_invoice_lines"),
    51: (migrate_v51, "po_lines.barcode nullable + CHECK, removes PRAGMA FK workaround in add_note()"),
    52: (migrate_v52, "drop unused password_hash column from users"),
    53: (migrate_v53, "backfill corrected checksums for migrate_v40 and migrate_v42"),
    54: (migrate_v54, "move schema_version from settings to dedicated db_meta table"),
    55: (migrate_v55, "no_negative_soh flag on departments (FRESH on); db_meta dedupe"),
    56: (migrate_v56, "online_available flag on products for shop.littleredapple.com.au"),
    57: (migrate_v57, "online_notes text field on products for shop product pages"),
    58: (migrate_v58, "received_weight column on po_lines for variable weight items"),
    59: (migrate_v59, "group_id on stocktake_sessions for sub-department filtering"),
    60: (migrate_v60, "atria_import_log table for startup Atria sync tracking"),
    61: (migrate_v61, "unmatched_count column on atria_import_log"),
}
