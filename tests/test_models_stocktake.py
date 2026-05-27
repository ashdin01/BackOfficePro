"""Tests for models/stocktake.py."""
import pytest
from database.connection import get_connection
import models.stocktake as stocktake_model
import models.stock_on_hand as soh_model


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
