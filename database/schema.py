SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS departments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);

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
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    abn             TEXT    DEFAULT '',
    rep_name        TEXT    DEFAULT '',
    rep_phone       TEXT    DEFAULT '',
    order_minimum   REAL    DEFAULT 0,
    email_orders    TEXT    DEFAULT '',
    email_admin     TEXT    DEFAULT '',
    email_accounts  TEXT    DEFAULT '',
    email_rep       TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS product_suppliers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode      TEXT    NOT NULL REFERENCES products(barcode),
    supplier_id  INTEGER NOT NULL REFERENCES suppliers(id),
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
    active        INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (department_id) REFERENCES departments(id),
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
    group_id        INTEGER REFERENCES product_groups(id),
    auto_reorder    INTEGER DEFAULT 0,
    FOREIGN KEY (department_id) REFERENCES departments(id),
    FOREIGN KEY (supplier_id)   REFERENCES suppliers(id)
);

CREATE INDEX IF NOT EXISTS idx_products_department ON products(department_id);
CREATE INDEX IF NOT EXISTS idx_products_supplier   ON products(supplier_id);
CREATE INDEX IF NOT EXISTS idx_products_base_sku   ON products(base_sku);

CREATE TABLE IF NOT EXISTS stock_on_hand (
    barcode         TEXT    PRIMARY KEY,
    quantity        REAL    NOT NULL DEFAULT 0,
    last_updated    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (barcode) REFERENCES products(barcode)
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
    FOREIGN KEY (barcode) REFERENCES products(barcode)
);

CREATE INDEX IF NOT EXISTS idx_movements_barcode ON stock_movements(barcode);
CREATE INDEX IF NOT EXISTS idx_movements_type    ON stock_movements(movement_type);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number       TEXT    NOT NULL UNIQUE,
    supplier_id     INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'DRAFT',
    delivery_date   DATE,
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent_at         DATETIME,
    received_at     DATETIME,
    created_by      TEXT,
    updated_at      DATETIME,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
);

CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_id);
CREATE INDEX IF NOT EXISTS idx_po_status   ON purchase_orders(status);

CREATE TABLE IF NOT EXISTS po_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id           INTEGER NOT NULL,
    barcode         TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    ordered_qty     REAL    NOT NULL,
    received_qty    REAL    NOT NULL DEFAULT 0,
    unit_cost       REAL    NOT NULL DEFAULT 0,
    notes           TEXT,
    actual_cost     REAL    DEFAULT 0,
    is_promo        INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (po_id)   REFERENCES purchase_orders(id),
    FOREIGN KEY (barcode) REFERENCES products(barcode)
);

CREATE INDEX IF NOT EXISTS idx_po_lines_po_id   ON po_lines(po_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_barcode ON po_lines(barcode);

CREATE TABLE IF NOT EXISTS barcode_aliases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_barcode  TEXT    NOT NULL UNIQUE,
    master_barcode TEXT    NOT NULL REFERENCES products(barcode),
    description    TEXT,
    created_at     TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stocktake_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT    NOT NULL,
    department_id   INTEGER,
    status          TEXT    NOT NULL DEFAULT 'OPEN',
    started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at       DATETIME,
    created_by      TEXT,
    notes           TEXT,
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE IF NOT EXISTS stocktake_counts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL,
    barcode         TEXT    NOT NULL,
    counted_qty     REAL    NOT NULL DEFAULT 0,
    scanned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES stocktake_sessions(id),
    FOREIGN KEY (barcode)    REFERENCES products(barcode)
);

CREATE INDEX IF NOT EXISTS idx_stocktake_counts_session ON stocktake_counts(session_id);
CREATE INDEX IF NOT EXISTS idx_stocktake_counts_barcode ON stocktake_counts(barcode);

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

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    full_name       TEXT,
    pin             TEXT,
    password_hash   TEXT,
    role            TEXT    NOT NULL DEFAULT 'STAFF',
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO users (username, full_name, role)
    VALUES ('admin', 'Administrator', 'ADMIN');

CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT,
    description     TEXT
);

INSERT OR IGNORE INTO settings (key, value, description) VALUES
    ('store_name',     'My Supermarket', 'Store trading name'),
    ('store_address',  '',               'Store address'),
    ('store_phone',    '',               'Store phone number'),
    ('store_abn',      '',               'Australian Business Number'),
    ('gst_rate',       '10.0',           'Default GST rate percentage'),
    ('currency',       'AUD',            'Currency code'),
    ('po_prefix',      'PO',             'Purchase order number prefix'),
    ('po_next_number', '1',              'Next PO sequence number'),
    ('po_pdf_path',    '',               'Folder path for exported PO PDFs'),
    ('schema_version', '14',             'Database schema version');
"""
