SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS departments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    no_negative_soh INTEGER NOT NULL DEFAULT 0 CHECK (no_negative_soh IN (0,1))
);

-- Seed must not reference no_negative_soh: this script runs against existing
-- databases BEFORE migrations, where the column does not exist yet (CREATE
-- TABLE IF NOT EXISTS above is a no-op there). migrate_v55 sets the FRESH
-- default instead.
INSERT OR IGNORE INTO departments (code, name) VALUES
    ('FRESH',   'Fresh'),
    ('MEAT',    'Meat'),
    ('SEAFOOD', 'Seafood'),
    ('DELI',    'Deli'),
    ('DAIRY',   'Dairy'),
    ('BAKERY',  'Bakery'),
    ('FROZEN',  'Frozen'),
    ('GROC',    'Grocery'),
    ('LIQ',     'Liquor'),
    ('GM',      'General Merchandise');

CREATE TABLE IF NOT EXISTS suppliers (
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

CREATE TABLE IF NOT EXISTS product_suppliers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode      TEXT    NOT NULL REFERENCES products(barcode) ON DELETE CASCADE,
    supplier_id  INTEGER NOT NULL REFERENCES suppliers(id)     ON DELETE CASCADE,
    is_default   INTEGER NOT NULL DEFAULT 0,
    supplier_sku TEXT    DEFAULT '',
    pack_qty     INTEGER DEFAULT 1,
    pack_unit    TEXT    DEFAULT 'EA',
    UNIQUE(barcode, supplier_id)
);

CREATE INDEX IF NOT EXISTS idx_product_suppliers_barcode   ON product_suppliers(barcode);
CREATE INDEX IF NOT EXISTS idx_product_suppliers_supplier  ON product_suppliers(supplier_id);

CREATE TABLE IF NOT EXISTS product_groups (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL,
    code          TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
    UNIQUE(department_id, code)
);

CREATE TABLE IF NOT EXISTS products (
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

CREATE INDEX IF NOT EXISTS idx_products_department ON products(department_id);
CREATE INDEX IF NOT EXISTS idx_products_supplier   ON products(supplier_id);
CREATE INDEX IF NOT EXISTS idx_products_base_sku   ON products(base_sku);

CREATE TABLE IF NOT EXISTS stock_on_hand (
    barcode         TEXT    PRIMARY KEY,
    quantity        REAL    NOT NULL DEFAULT 0,
    last_updated    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (barcode) REFERENCES products(barcode) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stock_movements (
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

CREATE INDEX IF NOT EXISTS idx_movements_barcode  ON stock_movements(barcode);
CREATE INDEX IF NOT EXISTS idx_movements_type     ON stock_movements(movement_type);
CREATE INDEX IF NOT EXISTS idx_movements_created  ON stock_movements(created_at DESC);

CREATE TABLE IF NOT EXISTS purchase_orders (
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

CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_id);
CREATE INDEX IF NOT EXISTS idx_po_status   ON purchase_orders(status);

CREATE TABLE IF NOT EXISTS po_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id           INTEGER NOT NULL,
    barcode         TEXT    DEFAULT NULL
                        CHECK (barcode IS NULL OR barcode != ''),
    description     TEXT    NOT NULL,
    ordered_qty     REAL    NOT NULL,
    received_qty    REAL    NOT NULL DEFAULT 0,
    received_weight REAL    NOT NULL DEFAULT 0,
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

CREATE INDEX IF NOT EXISTS idx_po_lines_po_id   ON po_lines(po_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_barcode ON po_lines(barcode);

CREATE TABLE IF NOT EXISTS barcode_aliases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_barcode  TEXT    NOT NULL UNIQUE,
    master_barcode TEXT    NOT NULL REFERENCES products(barcode) ON DELETE CASCADE,
    description    TEXT,
    created_at     TEXT    DEFAULT (datetime('now'))
);

-- Alternate selling configurations: case, 6-pack, etc. all drawing from the same
-- base-unit stock pool tracked on master_barcode.
CREATE TABLE IF NOT EXISTS product_selling_units (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    master_barcode TEXT    NOT NULL REFERENCES products(barcode) ON DELETE CASCADE,
    barcode        TEXT    UNIQUE,              -- scannable barcode (optional)
    plu            TEXT,                        -- PLU number (optional)
    label          TEXT    NOT NULL,            -- e.g. "Case (24×375ml)"
    unit_qty       REAL    NOT NULL DEFAULT 1 CHECK (unit_qty   > 0),  -- base units consumed per sale
    sell_price     REAL    NOT NULL DEFAULT 0 CHECK (sell_price >= 0),
    active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_selling_units_master  ON product_selling_units(master_barcode);
CREATE INDEX IF NOT EXISTS idx_selling_units_barcode ON product_selling_units(barcode);

CREATE TABLE IF NOT EXISTS stocktake_sessions (
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

CREATE TABLE IF NOT EXISTS stocktake_counts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL,
    barcode         TEXT    NOT NULL,
    counted_qty     REAL    NOT NULL DEFAULT 0,
    scanned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES stocktake_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (barcode)    REFERENCES products(barcode) ON DELETE CASCADE,
    UNIQUE(session_id, barcode)
);

CREATE INDEX IF NOT EXISTS idx_stocktake_counts_session ON stocktake_counts(session_id);
CREATE INDEX IF NOT EXISTS idx_stocktake_counts_barcode ON stocktake_counts(barcode);

CREATE TABLE IF NOT EXISTS bundles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    description  TEXT    DEFAULT '',
    required_qty INTEGER NOT NULL DEFAULT 4 CHECK (required_qty > 0),
    price        REAL    NOT NULL DEFAULT 0 CHECK (price >= 0),
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bundle_eligible (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_id   INTEGER NOT NULL,
    barcode     TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    unit_qty    INTEGER DEFAULT 1,
    FOREIGN KEY (bundle_id) REFERENCES bundles(id)       ON DELETE CASCADE,
    FOREIGN KEY (barcode)   REFERENCES products(barcode) ON DELETE CASCADE,
    UNIQUE(bundle_id, barcode)
);

CREATE INDEX IF NOT EXISTS idx_bundle_eligible_bundle ON bundle_eligible(bundle_id);
CREATE INDEX IF NOT EXISTS idx_bundle_eligible_barcode ON bundle_eligible(barcode);

CREATE TABLE IF NOT EXISTS plu_barcode_map (
    plu       INTEGER PRIMARY KEY,
    barcode   TEXT    NOT NULL,
    mapped_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sales_daily (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_date     TEXT    NOT NULL,
    plu           TEXT,
    plu_name      TEXT,
    sub_group     TEXT,
    weight_kg     REAL    DEFAULT 0,
    quantity      REAL    DEFAULT 0,
    nominal_price REAL    DEFAULT 0,
    discount      REAL    DEFAULT 0,
    rounding      REAL    DEFAULT 0,
    sales_dollars REAL    DEFAULT 0,
    sales_pct     REAL    DEFAULT 0,
    imported_at   TEXT    DEFAULT (datetime('now','localtime')),
    UNIQUE(sale_date, plu)
);

CREATE INDEX IF NOT EXISTS idx_sales_daily_plu_date ON sales_daily(plu, sale_date);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    full_name       TEXT,
    pin             TEXT,
    role            TEXT    NOT NULL DEFAULT 'STAFF'
                        CHECK (role IN ('ADMIN','MANAGER','STAFF')),
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO users (username, full_name, role)
    VALUES ('admin', 'Administrator', 'ADMIN');

CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT,
    description     TEXT
);

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
    payment_terms_days  INTEGER NOT NULL DEFAULT 37 CHECK (payment_terms_days >= 0),
    credit_limit        REAL DEFAULT 0              CHECK (credit_limit       >= 0),
    active              INTEGER NOT NULL DEFAULT 1  CHECK (active IN (0,1)),
    notes               TEXT DEFAULT '',
    created_at          TEXT DEFAULT (datetime('now','localtime')),
    updated_at          TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS ar_invoices (
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

CREATE TABLE IF NOT EXISTS ar_invoice_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL,
    barcode         TEXT DEFAULT NULL CHECK (barcode IS NULL OR barcode != ''),
    description     TEXT NOT NULL,
    quantity        REAL NOT NULL DEFAULT 1  CHECK (quantity    > 0),
    unit_price      REAL NOT NULL DEFAULT 0  CHECK (unit_price  >= 0),
    discount_pct    REAL NOT NULL DEFAULT 0  CHECK (discount_pct BETWEEN 0 AND 100),
    gst_rate        REAL NOT NULL DEFAULT 10 CHECK (gst_rate     BETWEEN 0 AND 100),
    line_subtotal   REAL NOT NULL DEFAULT 0,
    line_gst        REAL NOT NULL DEFAULT 0,
    line_total      REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (barcode)    REFERENCES products(barcode) ON DELETE RESTRICT
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
    payment_ref     TEXT UNIQUE,
    FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id)  ON DELETE RESTRICT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)    ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ar_credit_notes (
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
    FOREIGN KEY (customer_id) REFERENCES customers(id)   ON DELETE RESTRICT,
    FOREIGN KEY (invoice_id)  REFERENCES ar_invoices(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ar_invoices_customer   ON ar_invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_ar_invoices_status     ON ar_invoices(status);
CREATE INDEX IF NOT EXISTS idx_ar_invoice_lines_inv   ON ar_invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS idx_ar_payments_invoice    ON ar_payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_ar_payments_customer   ON ar_payments(customer_id);
CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_cust   ON ar_credit_notes(customer_id);
CREATE INDEX IF NOT EXISTS idx_ar_credit_notes_invoice ON ar_credit_notes(invoice_id);

INSERT OR IGNORE INTO settings (key, value, description) VALUES
    ('store_name',          'My Supermarket', 'Store trading name'),
    ('store_address',       '',               'Store address'),
    ('store_phone',         '',               'Store phone number'),
    ('store_abn',           '',               'Australian Business Number'),
    ('gst_rate',            '10.0',           'Default GST rate percentage'),
    ('currency',            'AUD',            'Currency code'),
    ('po_prefix',           'PO',             'Purchase order number prefix'),
    ('po_next_number',      '1',              'Next PO sequence number'),
    ('po_pdf_path',         '',               'Folder path for exported PO PDFs'),
    ('ar_next_invoice_number', '1',           'Next AR invoice sequence number'),
    ('ar_next_credit_number',  '1',           'Next AR credit note sequence number'),
    ('ar_invoice_pdf_path', '',               'Folder path for exported invoice PDFs')
ON CONFLICT(key) DO NOTHING;

-- Owned exclusively by the migration system.  Not in settings so that a bulk
-- DELETE FROM settings cannot destroy the version marker.
CREATE TABLE IF NOT EXISTS db_meta (
    version INTEGER NOT NULL DEFAULT 1
);
-- Seed only when the table is empty: db_meta has no unique constraint, so
-- INSERT OR IGNORE would append a duplicate row on every startup.
-- Seeded at 54 (not 55) so migrate_v55 also runs once on fresh installs:
-- this script cannot set departments.no_negative_soh defaults itself, since
-- it executes against pre-v55 databases where the column does not exist yet.
-- migrate_v55 is replay-safe (guarded ALTER, idempotent backfill).
INSERT INTO db_meta (version) SELECT 54 WHERE NOT EXISTS (SELECT 1 FROM db_meta);

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

CREATE INDEX IF NOT EXISTS idx_bank_txn_batch   ON bank_transactions(import_batch);
CREATE INDEX IF NOT EXISTS idx_bank_txn_status  ON bank_transactions(status);
CREATE INDEX IF NOT EXISTS idx_bank_txn_profile ON bank_transactions(profile_id);

CREATE TABLE IF NOT EXISTS po_charges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id           INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    description     TEXT NOT NULL DEFAULT '',
    tax_rate        REAL NOT NULL DEFAULT 0 CHECK (tax_rate BETWEEN 0 AND 100),
    amount_inc_tax  REAL NOT NULL DEFAULT 0 CHECK (amount_inc_tax >= 0)
);
CREATE INDEX IF NOT EXISTS idx_po_charges_po ON po_charges(po_id);

CREATE TABLE IF NOT EXISTS pos_sales (
    reference   TEXT    PRIMARY KEY,
    sale_date   TEXT    NOT NULL,
    operator    TEXT    NOT NULL DEFAULT '',
    received_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS migration_log (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    checksum    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity      TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    changed_by  TEXT NOT NULL DEFAULT '',
    changed_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_audit_entity     ON audit_log(entity, entity_key);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON audit_log(changed_at DESC);
"""
