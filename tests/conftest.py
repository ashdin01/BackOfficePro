"""
Shared pytest fixtures for BackOfficePro test suite.

Every test that touches the database receives a fresh, isolated SQLite DB
(via the test_db fixture).  The real DATABASE_PATH is patched so no test
ever reads or writes the production database.
"""
import sqlite3
import pytest
from database.schema import SCHEMA


# ── Core DB fixture ───────────────────────────────────────────────────────────

@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Create a temp database with the full schema and patch get_connection to use it."""
    db_path = str(tmp_path / "test.db")

    import database.connection as conn_module
    monkeypatch.setattr(conn_module, "DATABASE_PATH", db_path)

    # Apply schema (creates tables + inserts default departments, settings, admin user)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.close()

    yield db_path


@pytest.fixture()
def db_conn(test_db):
    """Live connection to the test database, closed after each test."""
    from database.connection import get_connection
    conn = get_connection()
    yield conn
    conn.close()


# ── Entity fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def dept_id(db_conn):
    """Return the id of the default GROC department."""
    row = db_conn.execute("SELECT id FROM departments WHERE code='GROC'").fetchone()
    return row["id"]


@pytest.fixture()
def supplier_id(db_conn):
    """Insert and return the id of a minimal test supplier."""
    db_conn.execute(
        "INSERT INTO suppliers (code, name) VALUES ('TST', 'Test Supplier')"
    )
    db_conn.commit()
    row = db_conn.execute("SELECT id FROM suppliers WHERE code='TST'").fetchone()
    return row["id"]


@pytest.fixture()
def product_barcode(db_conn, dept_id, supplier_id):
    """Insert a standard taxable product and return its barcode."""
    bc = "9300000000001"
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, 'Test Product', ?, ?, 3.50, 2.00, 10.0, 1, 'EA', 1, 'EA')
    """, (bc, dept_id, supplier_id))
    db_conn.commit()
    return bc


@pytest.fixture()
def gst_free_barcode(db_conn, dept_id, supplier_id):
    """Insert a GST-free product and return its barcode."""
    bc = "9300000000002"
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, 'GST Free Product', ?, ?, 2.00, 1.50, 0.0, 1, 'EA', 1, 'EA')
    """, (bc, dept_id, supplier_id))
    db_conn.commit()
    return bc
