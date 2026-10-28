import hashlib
import inspect
import logging
import marshal
import re
import sqlite3
import sys

from database.connection import get_connection

# Oldest schema version this code can upgrade.  Migrations below it were removed
# (they only ever ran on databases that have long since passed them), and new
# installs start at 54 — see the registry comment above _MIGRATIONS.
MIN_SUPPORTED_VERSION = 54


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


def _has_user_data(conn) -> bool:
    """True once the database holds any products — a brand-new install has
    nothing worth backing up before its first migrations."""
    try:
        return conn.execute("SELECT 1 FROM products LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False


def _log_migration(conn, version: int, description: str, fn):
    """Record a freshly-applied migration in migration_log."""
    conn.execute("""
        INSERT OR IGNORE INTO migration_log (version, applied_at, description, checksum)
        VALUES (?, datetime('now', 'localtime'), ?, ?)
    """, (version, description, _fn_checksum(fn)))
    conn.commit()


def _check_integrity(conn):
    """Verify migration log integrity against _MIGRATIONS.

    Two checks, both logged at WARNING only — neither blocks startup:
    - Gap: every version in _MIGRATIONS at or below schema_version must have a
      log entry.  A missing entry means a migration was skipped or the log was
      corrupted.  Gaps are expected on pre-log installs that haven't been
      backfilled yet.
    - Drift: for each logged version, recompute the checksum from the current
      function source and compare.  A mismatch usually just means a migration
      function's docstring/comments were reworded after being applied — or,
      structurally, that the checksum was originally stamped by a frozen
      (PyInstaller) build, which hashes bytecode since it can't retrieve its
      own source, while this recompute hashes source text: the exact same,
      byte-identical function then legitimately produces two different
      fingerprints. That case is guaranteed to "drift" for every migration a
      real store's database has ever had applied, since production databases
      are always migrated by the frozen exe — so this can never be treated as
      a reliable signal of an actual schema/code mismatch, only a hint worth
      a look.
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

    # Drift check — warn only, never blocks startup (see docstring: frozen-stamped
    # vs. source-recomputed checksums are not directly comparable, so this is a
    # hint, not a reliable signal). Still skipped entirely in frozen builds,
    # since there the recompute would use the bytecode-fallback path too and
    # add no information beyond what was stamped moments earlier.
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
            drifted.append(v)

    if drifted:
        logging.warning(
            f"Migration checksum drift for version(s): {sorted(drifted)} — "
            "recomputed checksum doesn't match what was stamped when applied. "
            "Often just a reworded docstring/comment, or a checksum originally "
            "stamped by a frozen build (see docstring). Not treated as fatal."
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

        if current < MIN_SUPPORTED_VERSION:
            raise RuntimeError(
                f"Database schema version {current} is older than the minimum "
                f"supported version {MIN_SUPPORTED_VERSION}. Open this database "
                f"once with BackOfficePro v2.23.0 (which still contains the full "
                f"migration chain), then upgrade."
            )

        if any(current < v for v in _MIGRATIONS) and _has_user_data(conn):
            # Never change a database that holds real data without a verified
            # copy to go back to.  Raises (aborting startup) if it can't be made.
            from controllers.backup_controller import pre_migration_backup
            db_file = conn.execute("PRAGMA database_list").fetchone()['file']
            saved = pre_migration_backup(db_file, current)
            logging.info(f"Pre-migration backup written: {saved}")

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


def migrate_v62(conn):
    """Add old_cost, new_cost, value_delta columns to stock_movements so a
    REVALUE row can record a product's cost-price change on PO receipt,
    plus its stock-value impact on the units already on hand at old cost."""
    _add_column(conn, "ALTER TABLE stock_movements ADD COLUMN old_cost REAL")
    _add_column(conn, "ALTER TABLE stock_movements ADD COLUMN new_cost REAL")
    _add_column(conn, "ALTER TABLE stock_movements ADD COLUMN value_delta REAL")
    conn.commit()


def migrate_v63(conn):
    """No-op. Re-stamped migration_log checksums for migrate_v40, v42 and v53-v62
    after their docstrings were reworded. v2-v54 have since been removed (see
    MIN_SUPPORTED_VERSION), and drift detection only checks versions still in
    _MIGRATIONS, so there is nothing left to re-stamp. Kept so the version
    sequence stays contiguous."""
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '63')")
    conn.commit()


def migrate_v64(conn):
    """Add rsa_cert_number, rsa_expiry_date to users so Responsible Service
    of Alcohol certification can be tracked and expiries surfaced as an
    upcoming task."""
    _add_column(conn, "ALTER TABLE users ADD COLUMN rsa_cert_number TEXT")
    _add_column(conn, "ALTER TABLE users ADD COLUMN rsa_expiry_date DATE")
    conn.commit()


def migrate_v65(conn):
    """Add supplier_id to stocktake_sessions so a stocktake can be scoped to
    everything a supplier sells, as an alternative to department/group scoping."""
    _add_column(conn, """
        ALTER TABLE stocktake_sessions ADD COLUMN supplier_id INTEGER
            REFERENCES suppliers(id) ON DELETE SET NULL
    """)
    conn.commit()


def migrate_v66(conn):
    """Add charge_type to po_charges (FREIGHT/FUEL_LEVY/ROUNDING/OTHER) and
    relax the amount_inc_tax CHECK so ROUNDING charges may be negative —
    every other charge type still must be >= 0.

    Existing rows are backfilled by matching their free-text description,
    falling back to OTHER when nothing matches. Table is recreated
    (rename-create-copy-drop) because SQLite can't ALTER an existing CHECK
    constraint.
    """
    conn.executescript("""
        PRAGMA foreign_keys       = OFF;
        PRAGMA legacy_alter_table = ON;
        BEGIN TRANSACTION;

        ALTER TABLE po_charges RENAME TO po_charges_old;
        CREATE TABLE po_charges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id           INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            charge_type     TEXT NOT NULL DEFAULT 'OTHER'
                                CHECK (charge_type IN ('FREIGHT','FUEL_LEVY','ROUNDING','OTHER')),
            description     TEXT NOT NULL DEFAULT '',
            tax_rate        REAL NOT NULL DEFAULT 0 CHECK (tax_rate BETWEEN 0 AND 100),
            amount_inc_tax  REAL NOT NULL DEFAULT 0
                                CHECK (amount_inc_tax >= 0 OR charge_type = 'ROUNDING')
        );
        INSERT INTO po_charges (id, po_id, charge_type, description, tax_rate, amount_inc_tax)
            SELECT id, po_id,
                   CASE
                       WHEN description LIKE 'freight%'  THEN 'FREIGHT'
                       WHEN description LIKE 'fuel%'     THEN 'FUEL_LEVY'
                       WHEN description LIKE 'round%'    THEN 'ROUNDING'
                       ELSE 'OTHER'
                   END,
                   description, tax_rate, MAX(amount_inc_tax, 0)
            FROM po_charges_old;
        DROP TABLE po_charges_old;

        CREATE INDEX IF NOT EXISTS idx_po_charges_po ON po_charges(po_id);

        COMMIT;
        PRAGMA legacy_alter_table = OFF;
        PRAGMA foreign_keys       = ON;
    """)
    conn.commit()


def migrate_v67(conn):
    """Add order_prep_include flag to products for the mobile Order Prep app.

    Products with order_prep_include = 1 appear on the phone's market order
    list for their linked supplier. Staff tag lines manually via the product
    list in BackOfficePro — typically the Fresh department's fruit & veg.
    """
    _add_column(conn, """
        ALTER TABLE products ADD COLUMN order_prep_include
            INTEGER NOT NULL DEFAULT 0 CHECK (order_prep_include IN (0,1))
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_products_order_prep ON products(order_prep_include)")
    conn.commit()


def migrate_v68(conn):
    """Add held_sales/held_sale_lines for the POS suspend/resume-sale feature.

    RetailPOSPro terminals share no local datastore, so held_sales is the
    cross-terminal source of truth for sales parked mid-transaction — a
    hold must be visible/resumable from any terminal, not just the one
    that created it.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS held_sales (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            reference      TEXT    NOT NULL UNIQUE,
            terminal_id    TEXT    NOT NULL,
            operator       TEXT    NOT NULL DEFAULT '',
            status         TEXT    NOT NULL DEFAULT 'OPEN'
                               CHECK (status IN ('OPEN','RESUMED','VOIDED')),
            note           TEXT    NOT NULL DEFAULT '',
            subtotal       REAL    NOT NULL DEFAULT 0,
            gst_amount     REAL    NOT NULL DEFAULT 0,
            total          REAL    NOT NULL DEFAULT 0,
            item_count     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            resumed_at     TEXT,
            resumed_by_terminal TEXT,
            voided_at      TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_held_sales_status ON held_sales(status)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS held_sale_lines (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            held_sale_id   INTEGER NOT NULL REFERENCES held_sales(id) ON DELETE CASCADE,
            barcode        TEXT    NOT NULL,
            description    TEXT    NOT NULL,
            qty            REAL    NOT NULL,
            unit_price     REAL    NOT NULL,
            tax_rate       REAL    NOT NULL DEFAULT 10.0,
            price_reason   TEXT    NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_held_sale_lines_parent ON held_sale_lines(held_sale_id)")
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('hold_prefix', 'HLD')")
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('hold_next_number', '1')")
    conn.commit()


def migrate_v69(conn):
    """Add product_batches table for per-batch use-by/best-before tracking.

    Deliberately alerting-only: records what came in and when it's due, but
    does not track FEFO depletion against stock_on_hand's single aggregate
    quantity — a batch is dismissed manually (resolved=1) once handled.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_batches (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode         TEXT    NOT NULL,
            po_line_id      INTEGER,
            received_date   DATE    NOT NULL,
            use_by_date     DATE    NOT NULL,
            qty_received    REAL    NOT NULL,
            resolved        INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0,1)),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (barcode)    REFERENCES products(barcode)  ON DELETE CASCADE,
            FOREIGN KEY (po_line_id) REFERENCES po_lines(id)       ON DELETE SET NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batches_use_by  ON product_batches(use_by_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batches_barcode ON product_batches(barcode)")
    conn.commit()


def migrate_v70(conn):
    """Add receipt-level and line-level pricing so a POS sale can be viewed as
    a full transaction later, not just individual per-product movements.

    RetailPOSPro already POSTs payment_method/subtotal/gst_amount/total and
    per-line unit_price/line_total/tax_rate to /api/v1/pos/sale, but
    record_pos_sale_atomic() was only ever persisting reference/sale_date/
    operator and quantity — the rest was received and discarded. This adds
    columns to keep it so "Movement History" can show a full receipt.
    """
    _add_column(conn, "ALTER TABLE pos_sales ADD COLUMN payment_method TEXT")
    _add_column(conn, "ALTER TABLE pos_sales ADD COLUMN subtotal REAL")
    _add_column(conn, "ALTER TABLE pos_sales ADD COLUMN gst_amount REAL")
    _add_column(conn, "ALTER TABLE pos_sales ADD COLUMN total REAL")
    _add_column(conn, "ALTER TABLE stock_movements ADD COLUMN unit_price REAL")
    _add_column(conn, "ALTER TABLE stock_movements ADD COLUMN line_total REAL")
    _add_column(conn, "ALTER TABLE stock_movements ADD COLUMN tax_rate REAL")
    conn.commit()


def migrate_v71(conn):
    """Add carton_sku to products — a per-product carton/case identifier,
    edited directly on Product Detail (distinct from the per-supplier SKU
    tracked in Manage Suppliers)."""
    _add_column(conn, "ALTER TABLE products ADD COLUMN carton_sku TEXT DEFAULT ''")
    conn.commit()


def migrate_v72(conn):
    """Add pos_refunds / pos_refund_lines — a POS cash refund's own idempotency
    ledger (mirrors pos_sales) plus per-line qty/line_total, needed so a
    refund can validate it never exceeds what pos_sales/stock_movements
    actually recorded as sold, even across several partial refunds of the
    same original sale."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pos_refunds (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            reference          TEXT NOT NULL UNIQUE,
            original_reference TEXT NOT NULL REFERENCES pos_sales(reference),
            refund_date        TEXT NOT NULL,
            operator           TEXT NOT NULL DEFAULT '',
            received_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            subtotal           REAL,
            gst_amount         REAL,
            total              REAL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pos_refunds_original "
        "ON pos_refunds(original_reference)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pos_refund_lines (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            refund_id  INTEGER NOT NULL REFERENCES pos_refunds(id),
            barcode    TEXT NOT NULL,
            qty        REAL NOT NULL,
            line_total REAL NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pos_refund_lines_refund "
        "ON pos_refund_lines(refund_id)"
    )
    conn.commit()


def migrate_v73(conn):
    """Backfill product_suppliers for products that have a supplier_id but no
    supplier link at all. Add Product used to set only products.supplier_id,
    so those products were invisible to PO item lookup (which joins
    product_suppliers) until someone re-saved them in Product Detail. Each
    gets its existing supplier as the default link, carrying over the
    product's supplier SKU and pack size. Products that already have any link
    are left untouched, so this is safe to re-run.

    A database whose FKs were left dangling by an older table-rebuild
    migration (product_suppliers -> "products_old") can't take the insert;
    skip with a warning rather than aborting startup."""
    try:
        conn.execute("""
            INSERT OR IGNORE INTO product_suppliers
                (barcode, supplier_id, is_default, supplier_sku, pack_qty, pack_unit)
            SELECT p.barcode, p.supplier_id, 1,
                   COALESCE(p.supplier_sku, ''),
                   COALESCE(NULLIF(p.pack_qty, 0), 1),
                   COALESCE(NULLIF(p.pack_unit, ''), 'ea')
            FROM products p
            JOIN suppliers s ON s.id = p.supplier_id
            WHERE p.supplier_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM product_suppliers ps WHERE ps.barcode = p.barcode)
        """)
    except sqlite3.OperationalError as e:
        logging.warning("migrate_v73: supplier-link backfill skipped (%s)", e)
    conn.commit()


def migrate_v74(conn):
    """Add po_lines.counted_units — units counted at the dock by the mobile
    receive app. Staging only: it changes no stock and no PO status; the
    desktop Receive dialog prefills from it and receive_atomic clears it."""
    _add_column(conn, "ALTER TABLE po_lines ADD COLUMN counted_units INTEGER DEFAULT NULL")
    conn.commit()


def migrate_v75(conn):
    """Add kit_components / kit_builds for pre-assembled kits (e.g. Xmas hampers).

    A kit is an ordinary product (own barcode/PLU/stock_on_hand) with a recipe of
    component products. Building a batch consumes the components and adds the
    finished kits in one transaction, so a sale only ever reduces the kit's own
    stock. kit_builds is the history; its id is the movement reference (ASM-<id>).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kit_components (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_barcode    TEXT NOT NULL,
            component_barcode TEXT NOT NULL,
            qty               REAL NOT NULL DEFAULT 1 CHECK (qty > 0),
            FOREIGN KEY (parent_barcode)    REFERENCES products(barcode) ON DELETE CASCADE,
            FOREIGN KEY (component_barcode) REFERENCES products(barcode) ON DELETE RESTRICT,
            UNIQUE (parent_barcode, component_barcode),
            CHECK (parent_barcode != component_barcode)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kit_components_parent    ON kit_components(parent_barcode)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kit_components_component ON kit_components(component_barcode)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kit_builds (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_barcode TEXT NOT NULL,
            qty            REAL NOT NULL CHECK (qty != 0),
            unit_cost      REAL,
            notes          TEXT DEFAULT '',
            created_by     TEXT DEFAULT '',
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_barcode) REFERENCES products(barcode) ON DELETE RESTRICT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kit_builds_parent ON kit_builds(parent_barcode)")
    conn.commit()


def migrate_v76(conn):
    """Add po_lines.received_units — the exact number of individual units
    received on a line.

    received_qty is a carton count that rounds a partial carton up (1 unit of a
    6-pack was recorded as 1 carton), so PO history, GST reports and PO reversal
    over-counted partial receipts. received_units is the authoritative figure
    for all PO types; received_qty is kept as the carton-rounded count.

    Backfill: where the PO's RECEIPT/RETURN stock movements for the barcode are
    consistent with the stored carton count (ceil(units / pack) == received_qty)
    the movement total is the exact unit figure — this recovers past partial
    receipts. Otherwise fall back to received_qty * pack_qty (RO/IO store units
    in received_qty already). Lines whose barcode appears more than once on the
    PO also use the fallback, as the movements can't be split between them.
    """
    import math
    _add_column(conn, "ALTER TABLE po_lines ADD COLUMN received_units INTEGER NOT NULL DEFAULT 0")

    rows = conn.execute("""
        SELECT pl.id, pl.barcode, pl.received_qty, COALESCE(pl.pack_qty, 1) AS pack_qty,
               po.po_number, po.po_type,
               (SELECT COUNT(*) FROM po_lines x
                 WHERE x.po_id = pl.po_id AND x.barcode = pl.barcode
                   AND x.received_qty > 0) AS same_barcode_lines
        FROM po_lines pl
        JOIN purchase_orders po ON po.id = pl.po_id
        WHERE pl.received_qty > 0 AND pl.is_note = 0
    """).fetchall()

    for r in rows:
        line_id, barcode, received_qty, pack, po_number, po_type, dupes = tuple(r)
        pack = max(1, int(pack or 1))
        received_qty = float(received_qty or 0)
        if po_type in ('RO', 'IO'):
            units = int(round(received_qty))
        else:
            units = int(round(received_qty * pack))
            if dupes == 1 and pack > 1:
                moved = conn.execute("""
                    SELECT COALESCE(SUM(ABS(quantity)), 0) FROM stock_movements
                    WHERE barcode = ? AND reference = ?
                      AND movement_type IN ('RECEIPT', 'RETURN')
                """, (barcode, po_number)).fetchone()[0]
                moved = int(round(moved or 0))
                if moved > 0 and math.ceil(moved / pack) == int(round(received_qty)):
                    units = moved
        conn.execute("UPDATE po_lines SET received_units = ? WHERE id = ?", (units, line_id))
    conn.commit()


# ── Migration registry ────────────────────────────────────────────────────────
# Maps version number → (function, description).
# Entries are applied in sorted version order by apply_migrations().
# Never reorder entries; only append new ones.
#
# Migrations v2-v54 were removed once every database in use had passed them.
# New installs are created from database.schema.SCHEMA (seeded at version 54),
# so only v55 onwards ever runs.  A database older than MIN_SUPPORTED_VERSION
# must first be opened with BackOfficePro v2.23.0 (the last release that still
# contains the full chain) so it can be brought up to date.

_MIGRATIONS: dict[int, tuple] = {
    55: (migrate_v55, "no_negative_soh flag on departments (FRESH on); db_meta dedupe"),
    56: (migrate_v56, "online_available flag on products for shop.littleredapple.com.au"),
    57: (migrate_v57, "online_notes text field on products for shop product pages"),
    58: (migrate_v58, "received_weight column on po_lines for variable weight items"),
    59: (migrate_v59, "group_id on stocktake_sessions for sub-department filtering"),
    60: (migrate_v60, "atria_import_log table for startup Atria sync tracking"),
    61: (migrate_v61, "unmatched_count column on atria_import_log"),
    62: (migrate_v62, "old_cost/new_cost/value_delta columns on stock_movements for REVALUE tracking"),
    63: (migrate_v63, "backfill corrected checksums for migrate_v40, v42, and v53-v62"),
    64: (migrate_v64, "rsa_cert_number, rsa_expiry_date columns on users"),
    65: (migrate_v65, "supplier_id on stocktake_sessions for by-supplier stocktake scoping"),
    66: (migrate_v66, "po_charges.charge_type (freight/fuel levy/rounding/other) + negative amount allowed for rounding"),
    67: (migrate_v67, "order_prep_include flag on products for the mobile Order Prep app"),
    68: (migrate_v68, "held_sales, held_sale_lines tables for POS hold/resume"),
    69: (migrate_v69, "product_batches table for per-batch use-by/best-before tracking"),
    70: (migrate_v70, "pos_sales totals + stock_movements unit_price/line_total/tax_rate for full-transaction view"),
    71: (migrate_v71, "carton_sku column on products"),
    72: (migrate_v72, "pos_refunds, pos_refund_lines tables for POS cash refunds"),
    73: (migrate_v73, "backfill product_suppliers link for products with a supplier_id but no link"),
    74: (migrate_v74, "counted_units on po_lines for mobile receive staging"),
    75: (migrate_v75, "kit_components, kit_builds for pre-assembled kits (Xmas hampers)"),
    76: (migrate_v76, "received_units on po_lines (exact units received; backfilled from stock movements)"),
}
