"""Tests for models/stocktake.py."""
import sqlite3 as _sqlite3
import pytest
from database.connection import get_connection
import models.stocktake as stocktake_model
import models.stock_on_hand as soh_model


# ── Fresh-department fixtures (mirrors tests/test_negative_soh_clamp.py) ──────

@pytest.fixture()
def fresh_dept_id(db_conn):
    """The FRESH department with no_negative_soh enabled."""
    db_conn.execute("UPDATE departments SET no_negative_soh=1 WHERE code='FRESH'")
    db_conn.commit()
    row = db_conn.execute("SELECT id FROM departments WHERE code='FRESH'").fetchone()
    return row["id"]


@pytest.fixture()
def fresh_barcode(db_conn, fresh_dept_id, supplier_id):
    """A product in the Fresh department."""
    bc = "9300000000078"
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, 'Fresh Pears', ?, ?, 4.50, 2.00, 0.0, 1, 'KG', 1, 'KG')
    """, (bc, fresh_dept_id, supplier_id))
    db_conn.commit()
    return bc


# ── Local fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def session_id(test_db):
    """Create an OPEN stocktake session and return its id."""
    return stocktake_model.create_session(
        label="Test Session",
        notes="Test notes",
        created_by="admin",
    )


# ── TestCreateSession ─────────────────────────────────────────────────────────

class TestCreateSession:
    def test_create_session_returns_int_id(self, test_db):
        sid = stocktake_model.create_session("My Session")
        assert isinstance(sid, int)
        assert sid > 0

    def test_get_session_returns_open_status(self, test_db, session_id):
        row = stocktake_model.get_session(session_id)
        assert row is not None
        assert row["status"] == "OPEN"

    def test_get_all_sessions_includes_new_session(self, test_db, session_id):
        sessions = stocktake_model.get_all_sessions()
        ids = [s["id"] for s in sessions]
        assert session_id in ids

    def test_create_session_stores_notes_and_created_by(self, test_db):
        sid = stocktake_model.create_session(
            label="Labelled Session",
            notes="My stocktake notes",
            created_by="jane",
        )
        row = stocktake_model.get_session(sid)
        assert row["notes"] == "My stocktake notes"
        assert row["created_by"] == "jane"


# ── TestCloseSession ──────────────────────────────────────────────────────────

class TestCloseSession:
    def test_close_session_sets_closed_status(self, test_db, session_id):
        stocktake_model.close_session(session_id)
        row = stocktake_model.get_session(session_id)
        assert row["status"] == "CLOSED"

    def test_get_session_after_close_shows_closed(self, test_db, session_id):
        stocktake_model.close_session(session_id)
        row = stocktake_model.get_session(session_id)
        assert row is not None
        assert row["status"] == "CLOSED"


# ── TestCounts ────────────────────────────────────────────────────────────────

class TestCounts:
    def test_upsert_count_inserts_new_row(self, test_db, session_id, product_barcode):
        stocktake_model.upsert_count(session_id, product_barcode, 10.0)
        qty = stocktake_model.get_count_for_barcode(session_id, product_barcode)
        assert qty == pytest.approx(10.0)

    def test_upsert_count_again_accumulates_qty(self, test_db, session_id, product_barcode):
        stocktake_model.upsert_count(session_id, product_barcode, 5.0)
        stocktake_model.upsert_count(session_id, product_barcode, 3.0)
        qty = stocktake_model.get_count_for_barcode(session_id, product_barcode)
        assert qty == pytest.approx(8.0)

    def test_get_count_for_barcode_returns_correct_qty(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 42.0)
        assert stocktake_model.get_count_for_barcode(
            session_id, product_barcode
        ) == pytest.approx(42.0)

    def test_get_count_for_barcode_returns_zero_when_none(
        self, test_db, session_id, product_barcode
    ):
        assert stocktake_model.get_count_for_barcode(
            session_id, product_barcode
        ) == pytest.approx(0.0)

    def test_get_counts_returns_row_with_description(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 7.0)
        rows = stocktake_model.get_counts(session_id)
        assert len(rows) == 1
        assert rows[0]["barcode"] == product_barcode
        assert rows[0]["description"] is not None

    def test_delete_count_removes_it(self, test_db, session_id, product_barcode):
        stocktake_model.upsert_count(session_id, product_barcode, 5.0)
        rows = stocktake_model.get_counts(session_id)
        count_id = rows[0]["id"]
        stocktake_model.delete_count(count_id)
        qty = stocktake_model.get_count_for_barcode(session_id, product_barcode)
        assert qty == pytest.approx(0.0)


# ── TestApplySession ──────────────────────────────────────────────────────────

class TestApplySession:
    def test_apply_session_writes_counted_qty_to_soh(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 25.0)
        stocktake_model.apply_session(session_id)
        soh = soh_model.get_by_barcode(product_barcode)
        assert soh is not None
        assert soh["quantity"] == pytest.approx(25.0)

    def test_apply_session_creates_stocktake_movement(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 10.0)
        stocktake_model.apply_session(session_id)
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=? AND movement_type='STOCKTAKE'",
            (product_barcode,),
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_apply_session_sets_session_to_closed(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 5.0)
        stocktake_model.apply_session(session_id)
        row = stocktake_model.get_session(session_id)
        assert row["status"] == "CLOSED"

    def test_apply_session_already_closed_raises(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 5.0)
        stocktake_model.apply_session(session_id)
        with pytest.raises(ValueError):
            stocktake_model.apply_session(session_id)

    def test_apply_session_nonexistent_raises(self, test_db):
        with pytest.raises(ValueError):
            stocktake_model.apply_session(99999)


# ── TestApplySessionClamp ─────────────────────────────────────────────────────

class TestApplySessionClamp:
    def test_apply_session_clamps_fresh_product_to_zero(
        self, test_db, db_conn, session_id, fresh_barcode
    ):
        # A counted qty below zero (e.g. a correction entry) is written
        # straight to stock_on_hand by apply_session, so it must be clamped.
        stocktake_model.upsert_count(session_id, fresh_barcode, -4.0)
        stocktake_model.apply_session(session_id)
        soh = soh_model.get_by_barcode(fresh_barcode)
        assert soh["quantity"] == pytest.approx(0.0)

    def test_apply_session_clamp_records_compensating_movement(
        self, test_db, db_conn, session_id, fresh_barcode
    ):
        stocktake_model.upsert_count(session_id, fresh_barcode, -4.0)
        stocktake_model.apply_session(session_id)
        moves = db_conn.execute(
            "SELECT movement_type, quantity FROM stock_movements"
            " WHERE barcode=? ORDER BY id",
            (fresh_barcode,),
        ).fetchall()
        assert [(m["movement_type"], m["quantity"]) for m in moves] == [
            ("STOCKTAKE", -4), ("ADJUSTMENT_IN", 4),
        ]

    def test_apply_session_non_fresh_product_can_go_negative(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, -3.0)
        stocktake_model.apply_session(session_id)
        soh = soh_model.get_by_barcode(product_barcode)
        assert soh["quantity"] == pytest.approx(-3.0)


# ── TestVarianceReport ────────────────────────────────────────────────────────

class TestVarianceReport:
    def test_variance_report_includes_uncounted_product(
        self, test_db, session_id, product_barcode
    ):
        # product_barcode is active and expected=1 (default), not yet counted
        rows = stocktake_model.get_variance_report(session_id)
        barcodes = [r["barcode"] for r in rows]
        assert product_barcode in barcodes

    def test_variance_report_uncounted_product_has_none_counted_qty(
        self, test_db, session_id, product_barcode
    ):
        rows = stocktake_model.get_variance_report(session_id)
        row = next(r for r in rows if r["barcode"] == product_barcode)
        assert row["counted_qty"] is None

    def test_variance_report_after_upsert_shows_counted_qty(
        self, test_db, session_id, product_barcode
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 15.0)
        rows = stocktake_model.get_variance_report(session_id)
        row = next(r for r in rows if r["barcode"] == product_barcode)
        assert row["counted_qty"] == pytest.approx(15.0)


# ── TestUpsertClosed ──────────────────────────────────────────────────────────

class TestUpsertClosed:
    def test_upsert_on_closed_session_raises(self, test_db, session_id, product_barcode):
        stocktake_model.close_session(session_id)
        with pytest.raises(ValueError, match="not open"):
            stocktake_model.upsert_count(session_id, product_barcode, 5.0)

    def test_upsert_on_nonexistent_session_raises(self, test_db, product_barcode):
        with pytest.raises(ValueError):
            stocktake_model.upsert_count(99999, product_barcode, 5.0)


# ── TestVarianceReportDeptFilter ──────────────────────────────────────────────

class TestVarianceReportDeptFilter:
    def test_dept_filtered_session_includes_matching_product(
        self, test_db, product_barcode, dept_id
    ):
        sid = stocktake_model.create_session("Dept Session", department_id=dept_id)
        rows = stocktake_model.get_variance_report(sid)
        assert any(r["barcode"] == product_barcode for r in rows)

    def test_dept_filtered_session_excludes_other_dept_product(
        self, test_db, product_barcode, db_conn
    ):
        db_conn.execute("INSERT INTO departments (code, name) VALUES ('LIQUOR', 'Liquor')")
        db_conn.commit()
        other_id = db_conn.execute(
            "SELECT id FROM departments WHERE code='LIQUOR'"
        ).fetchone()["id"]
        sid = stocktake_model.create_session("Other Dept", department_id=other_id)
        rows = stocktake_model.get_variance_report(sid)
        assert not any(r["barcode"] == product_barcode for r in rows)


class TestVarianceReportGroupFilter:
    def test_group_filtered_session_includes_matching_product(
        self, test_db, db_conn, dept_id, product_barcode
    ):
        db_conn.execute(
            "INSERT INTO product_groups (department_id, code, name) VALUES (?, 'MILK', 'Milk')",
            (dept_id,)
        )
        db_conn.commit()
        group_id = db_conn.execute(
            "SELECT id FROM product_groups WHERE code='MILK'"
        ).fetchone()["id"]
        db_conn.execute(
            "UPDATE products SET group_id=? WHERE barcode=?", (group_id, product_barcode)
        )
        db_conn.commit()

        sid = stocktake_model.create_session("Group Session", group_id=group_id)
        rows = stocktake_model.get_variance_report(sid)
        assert any(r["barcode"] == product_barcode for r in rows)

    def test_group_filtered_session_excludes_other_group_product(
        self, test_db, db_conn, dept_id, product_barcode
    ):
        db_conn.execute(
            "INSERT INTO product_groups (department_id, code, name) VALUES (?, 'MILK', 'Milk')",
            (dept_id,)
        )
        db_conn.execute(
            "INSERT INTO product_groups (department_id, code, name) VALUES (?, 'BREAD', 'Bread')",
            (dept_id,)
        )
        db_conn.commit()
        milk_id = db_conn.execute(
            "SELECT id FROM product_groups WHERE code='MILK'"
        ).fetchone()["id"]
        bread_id = db_conn.execute(
            "SELECT id FROM product_groups WHERE code='BREAD'"
        ).fetchone()["id"]
        db_conn.execute(
            "UPDATE products SET group_id=? WHERE barcode=?", (bread_id, product_barcode)
        )
        db_conn.commit()

        sid = stocktake_model.create_session("Milk Session", group_id=milk_id)
        rows = stocktake_model.get_variance_report(sid)
        assert not any(r["barcode"] == product_barcode for r in rows)


# ── TestImportFromCsv ─────────────────────────────────────────────────────────

class TestImportFromCsv:
    def test_happy_path(self, test_db, session_id, product_barcode, tmp_path):
        f = tmp_path / "counts.csv"
        f.write_text("barcode,qty\n9300000000001,10\n")
        imported, skipped, errors = stocktake_model.import_from_csv(session_id, str(f))
        assert imported == 1
        assert skipped == 0
        assert errors == []
        assert stocktake_model.get_count_for_barcode(session_id, product_barcode) == pytest.approx(10.0)

    def test_accumulates_onto_existing_count(
        self, test_db, session_id, product_barcode, tmp_path
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 5.0)
        f = tmp_path / "counts.csv"
        f.write_text("barcode,qty\n9300000000001,3\n")
        stocktake_model.import_from_csv(session_id, str(f))
        assert stocktake_model.get_count_for_barcode(session_id, product_barcode) == pytest.approx(8.0)

    def test_alias_barcode_resolves_to_master(
        self, test_db, session_id, product_barcode, db_conn, tmp_path
    ):
        alias = "9300000000099"
        db_conn.execute(
            "INSERT INTO barcode_aliases (alias_barcode, master_barcode) VALUES (?, ?)",
            (alias, product_barcode),
        )
        db_conn.commit()
        f = tmp_path / "alias.csv"
        f.write_text(f"barcode,qty\n{alias},7\n")
        imported, skipped, errors = stocktake_model.import_from_csv(session_id, str(f))
        assert imported == 1
        assert stocktake_model.get_count_for_barcode(session_id, product_barcode) == pytest.approx(7.0)

    def test_unknown_barcode_is_skipped_with_error(self, test_db, session_id, tmp_path):
        f = tmp_path / "unk.csv"
        f.write_text("barcode,qty\n9999999999999,5\n")
        imported, skipped, errors = stocktake_model.import_from_csv(session_id, str(f))
        assert imported == 0
        assert skipped == 1
        assert any("9999999999999" in e for e in errors)

    def test_bad_qty_is_skipped_with_error(
        self, test_db, session_id, product_barcode, tmp_path
    ):
        f = tmp_path / "bad.csv"
        f.write_text("barcode,qty\n9300000000001,notanumber\n")
        imported, skipped, errors = stocktake_model.import_from_csv(session_id, str(f))
        assert skipped == 1
        assert any("Bad qty" in e for e in errors)

    def test_empty_barcode_row_is_skipped(self, test_db, session_id, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("barcode,qty\n,5\n")
        imported, skipped, errors = stocktake_model.import_from_csv(session_id, str(f))
        assert imported == 0
        assert skipped == 1

    def test_missing_barcode_column_raises(self, test_db, session_id, tmp_path):
        f = tmp_path / "nobc.csv"
        f.write_text("sku,qty\n123,5\n")
        with pytest.raises(ValueError, match="[Bb]arcode"):
            stocktake_model.import_from_csv(session_id, str(f))

    def test_missing_qty_column_raises(self, test_db, session_id, tmp_path):
        f = tmp_path / "noqty.csv"
        f.write_text("barcode,price\n9300000000001,5.99\n")
        with pytest.raises(ValueError, match="[Qq]uantity"):
            stocktake_model.import_from_csv(session_id, str(f))


# ── TestImportFromSqlite ──────────────────────────────────────────────────────

def _make_ext_db(path, rows, table="counts", bc_col="barcode", qty_col="qty"):
    """Create a minimal external SQLite file for import tests."""
    conn = _sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table} ({bc_col} TEXT, {qty_col} REAL)")
    conn.executemany(f"INSERT INTO {table} VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


class TestImportFromSqlite:
    def test_happy_path(self, test_db, session_id, product_barcode, tmp_path):
        _make_ext_db(tmp_path / "ext.db", [(product_barcode, 8.0)])
        imported, skipped, errors = stocktake_model.import_from_sqlite(
            session_id, str(tmp_path / "ext.db")
        )
        assert imported == 1
        assert errors == []
        assert stocktake_model.get_count_for_barcode(session_id, product_barcode) == pytest.approx(8.0)

    def test_accumulates_onto_existing_count(
        self, test_db, session_id, product_barcode, tmp_path
    ):
        stocktake_model.upsert_count(session_id, product_barcode, 4.0)
        _make_ext_db(tmp_path / "ext.db", [(product_barcode, 6.0)])
        stocktake_model.import_from_sqlite(session_id, str(tmp_path / "ext.db"))
        assert stocktake_model.get_count_for_barcode(session_id, product_barcode) == pytest.approx(10.0)

    def test_alias_resolves_to_master(
        self, test_db, session_id, product_barcode, db_conn, tmp_path
    ):
        alias = "9300000000088"
        db_conn.execute(
            "INSERT INTO barcode_aliases (alias_barcode, master_barcode) VALUES (?, ?)",
            (alias, product_barcode),
        )
        db_conn.commit()
        _make_ext_db(tmp_path / "ext.db", [(alias, 3.0)])
        imported, skipped, errors = stocktake_model.import_from_sqlite(
            session_id, str(tmp_path / "ext.db")
        )
        assert imported == 1
        assert stocktake_model.get_count_for_barcode(session_id, product_barcode) == pytest.approx(3.0)

    def test_no_tables_raises(self, test_db, session_id, tmp_path):
        _sqlite3.connect(str(tmp_path / "empty.db")).close()
        with pytest.raises(ValueError, match="No tables"):
            stocktake_model.import_from_sqlite(session_id, str(tmp_path / "empty.db"))

    def test_no_suitable_table_raises(self, test_db, session_id, tmp_path):
        conn = _sqlite3.connect(str(tmp_path / "nomap.db"))
        conn.execute("CREATE TABLE data (sku TEXT, price REAL)")
        conn.commit()
        conn.close()
        with pytest.raises(ValueError, match="No suitable table"):
            stocktake_model.import_from_sqlite(session_id, str(tmp_path / "nomap.db"))

    def test_table_name_with_bracket_raises_value_error(self, test_db, session_id, tmp_path):
        """A table name containing ']' would break the bracket-quoted SQL
        used to read it — rejected before any query is built."""
        ext_path = tmp_path / "evil.db"
        conn = _sqlite3.connect(str(ext_path))
        conn.execute('CREATE TABLE "my]table" (barcode TEXT, qty REAL)')
        conn.commit()
        conn.close()
        with pytest.raises(ValueError, match="Unsafe identifier"):
            stocktake_model.import_from_sqlite(session_id, str(ext_path))

    def test_unknown_barcode_is_skipped(self, test_db, session_id, tmp_path):
        _make_ext_db(tmp_path / "ext.db", [("9999999999999", 5.0)])
        imported, skipped, errors = stocktake_model.import_from_sqlite(
            session_id, str(tmp_path / "ext.db")
        )
        assert skipped == 1
        assert any("9999999999999" in e for e in errors)

    def test_bad_qty_is_skipped(self, test_db, session_id, product_barcode, tmp_path):
        conn = _sqlite3.connect(str(tmp_path / "bad.db"))
        conn.execute("CREATE TABLE counts (barcode TEXT, qty TEXT)")
        conn.execute("INSERT INTO counts VALUES (?, ?)", (product_barcode, "notanumber"))
        conn.commit()
        conn.close()
        imported, skipped, errors = stocktake_model.import_from_sqlite(
            session_id, str(tmp_path / "bad.db")
        )
        assert skipped == 1
        assert any("Bad qty" in e for e in errors)

    def test_empty_barcode_is_skipped(self, test_db, session_id, tmp_path):
        _make_ext_db(tmp_path / "ext.db", [("", 5.0)])
        imported, skipped, errors = stocktake_model.import_from_sqlite(
            session_id, str(tmp_path / "ext.db")
        )
        assert imported == 0
        assert skipped == 1
