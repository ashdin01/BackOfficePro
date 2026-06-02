"""Tests for models/stock_on_hand.py — stock adjustments and audit trail."""
import pytest
from database.connection import get_connection
import models.stock_on_hand as soh_model


class TestRecordPosSaleAtomicDateValidation:
    """record_pos_sale_atomic must reject non-YYYY-MM-DD dates before any DB write."""

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "29-01-2026",
        "2026/01/01",
        "2026-13-01",   # month 13
        "2026-01-32",   # day 32
        "",
        None,
    ])
    def test_rejects_invalid_date(self, test_db, product_barcode, bad_date):
        with pytest.raises(ValueError, match="sale_date"):
            soh_model.record_pos_sale_atomic(
                "BAD-DATE-REF", bad_date, "test",
                [{"barcode": product_barcode, "qty": 1, "line_total": 1.0, "description": ""}],
            )

    def test_accepts_valid_date(self, test_db, product_barcode):
        result = soh_model.record_pos_sale_atomic(
            "VALID-DATE-REF", "2026-01-15", "test",
            [{"barcode": product_barcode, "qty": 1, "line_total": 1.0, "description": ""}],
        )
        assert result is True


class TestGetByBarcode:
    def test_returns_none_for_unknown_barcode(self, test_db):
        assert soh_model.get_by_barcode("0000000000000") is None

    def test_returns_record_after_adjustment(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 5, "RECEIPT", "PO-001", "", "admin")
        record = soh_model.get_by_barcode(product_barcode)
        assert record is not None
        assert record["quantity"] == 5


class TestAdjust:
    def test_positive_adjustment_increases_stock(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 10, "RECEIPT", "PO-001", "", "admin")
        assert soh_model.get_by_barcode(product_barcode)["quantity"] == 10

    def test_negative_adjustment_decreases_stock(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 10, "RECEIPT", "PO-001", "", "admin")
        soh_model.adjust(product_barcode, -3, "SALE", "SALE-001", "", "admin")
        assert soh_model.get_by_barcode(product_barcode)["quantity"] == 7

    def test_multiple_adjustments_accumulate_correctly(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 20, "RECEIPT", "PO-001", "", "admin")
        soh_model.adjust(product_barcode, -5, "SALE", "SALE-001", "", "admin")
        soh_model.adjust(product_barcode, -2, "WASTAGE", "WAST-001", "", "admin")
        soh_model.adjust(product_barcode, 3, "RETURN", "RET-001", "", "admin")
        assert soh_model.get_by_barcode(product_barcode)["quantity"] == 16

    def test_adjust_creates_movement_record(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 5, "RECEIPT", "PO-TEST", "a note", "admin")
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=?", (product_barcode,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["quantity"] == 5
        assert row["movement_type"] == "RECEIPT"
        assert row["reference"] == "PO-TEST"
        assert row["notes"] == "a note"
        assert row["created_by"] == "admin"

    def test_adjust_records_every_movement(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 10, "RECEIPT", "PO-001", "", "admin")
        soh_model.adjust(product_barcode, -3, "SALE", "SALE-001", "", "admin")
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=? ORDER BY id",
            (product_barcode,)
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0]["quantity"] == 10
        assert rows[1]["quantity"] == -3

    def test_adjust_creates_soh_record_if_none_exists(self, test_db, product_barcode):
        assert soh_model.get_by_barcode(product_barcode) is None
        soh_model.adjust(product_barcode, 1, "RECEIPT", "", "", "admin")
        assert soh_model.get_by_barcode(product_barcode) is not None


class TestGetBelowReorder:
    def test_product_at_reorder_point_is_included(self, test_db, product_barcode, db_conn):
        db_conn.execute(
            "UPDATE products SET reorder_point=10 WHERE barcode=?", (product_barcode,)
        )
        db_conn.commit()
        soh_model.adjust(product_barcode, 10, "RECEIPT", "", "", "admin")
        results = soh_model.get_below_reorder()
        barcodes = [r["barcode"] for r in results]
        assert product_barcode in barcodes

    def test_product_below_reorder_point_is_included(self, test_db, product_barcode, db_conn):
        db_conn.execute(
            "UPDATE products SET reorder_point=10 WHERE barcode=?", (product_barcode,)
        )
        db_conn.commit()
        soh_model.adjust(product_barcode, 5, "RECEIPT", "", "", "admin")
        results = soh_model.get_below_reorder()
        assert any(r["barcode"] == product_barcode for r in results)

    def test_product_above_reorder_point_excluded(self, test_db, product_barcode, db_conn):
        db_conn.execute(
            "UPDATE products SET reorder_point=5 WHERE barcode=?", (product_barcode,)
        )
        db_conn.commit()
        soh_model.adjust(product_barcode, 20, "RECEIPT", "", "", "admin")
        results = soh_model.get_below_reorder()
        assert not any(r["barcode"] == product_barcode for r in results)

    def test_product_with_zero_reorder_point_and_zero_stock_is_included(self, test_db, product_barcode):
        # get_below_reorder does not exclude reorder_point=0 products.
        # qty=0, reorder_point=0 satisfies qty <= reorder_point so the product appears.
        # Filtering by reorder_point > 0 is enforced in the controller, not the model.
        soh_model.adjust(product_barcode, 0, "RECEIPT", "", "", "admin")
        results = soh_model.get_below_reorder()
        assert any(r["barcode"] == product_barcode for r in results)


# ── get_by_barcodes edge cases ────────────────────────────────────────────────

class TestGetByBarcodes:
    def test_empty_list_returns_empty_dict(self, test_db):
        assert soh_model.get_by_barcodes([]) == {}

    def test_returns_quantities_for_known_barcodes(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 10, "RECEIPT", "", "", "")
        result = soh_model.get_by_barcodes([product_barcode])
        assert product_barcode in result
        assert result[product_barcode] == pytest.approx(10.0)

    def test_unknown_barcode_not_in_result(self, test_db, product_barcode):
        result = soh_model.get_by_barcodes([product_barcode, '0000000000000'])
        assert '0000000000000' not in result


# ── record_pos_sale_atomic ────────────────────────────────────────────────────

class TestRecordPosSaleAtomic:
    def test_happy_path_returns_true_and_reduces_stock(
        self, test_db, product_barcode, db_conn
    ):
        db_conn.execute(
            "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 20)",
            (product_barcode,)
        )
        db_conn.commit()
        items = [{'barcode': product_barcode, 'qty': 3, 'line_total': 10.50, 'description': 'Test'}]
        result = soh_model.record_pos_sale_atomic('REF-001', '2026-05-01', 'cashier', items)
        assert result is True
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        assert row["quantity"] == pytest.approx(17.0)

    def test_duplicate_reference_returns_false(
        self, test_db, product_barcode, db_conn
    ):
        db_conn.execute(
            "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 20)",
            (product_barcode,)
        )
        db_conn.commit()
        items = [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50, 'description': 'T'}]
        soh_model.record_pos_sale_atomic('REF-DUP', '2026-05-01', 'cashier', items)
        result = soh_model.record_pos_sale_atomic('REF-DUP', '2026-05-01', 'cashier', items)
        assert result is False

    def test_invalid_sale_date_raises(self, test_db, product_barcode):
        items = [{'barcode': product_barcode, 'qty': 1, 'line_total': 1.0, 'description': 'X'}]
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            soh_model.record_pos_sale_atomic('REF-BAD', 'not-a-date', 'cashier', items)

    def test_zero_qty_item_skipped(self, test_db, product_barcode, db_conn):
        db_conn.execute(
            "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 10)",
            (product_barcode,)
        )
        db_conn.commit()
        items = [{'barcode': product_barcode, 'qty': 0, 'line_total': 0, 'description': 'X'}]
        soh_model.record_pos_sale_atomic('REF-ZERO', '2026-05-01', 'cashier', items)
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        # qty=0 is skipped — SOH unchanged
        assert row["quantity"] == pytest.approx(10.0)

    def test_selling_unit_uses_master_barcode(
        self, test_db, product_barcode, db_conn
    ):
        su_bc = '9300000099888'
        db_conn.execute("""
            INSERT INTO product_selling_units
                (master_barcode, barcode, label, unit_qty, sell_price, active)
            VALUES (?, ?, '2-pack', 2, 7.00, 1)
        """, (product_barcode, su_bc))
        db_conn.execute(
            "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 10)",
            (product_barcode,)
        )
        db_conn.commit()
        items = [{'barcode': su_bc, 'qty': 1, 'line_total': 7.00, 'description': '2-pack'}]
        soh_model.record_pos_sale_atomic('REF-SU', '2026-05-01', 'cashier', items)
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        # 1 selling unit = 2 master units consumed
        assert row["quantity"] == pytest.approx(8.0)
