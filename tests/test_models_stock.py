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
    def test_product_at_reorder_point_not_yet_included(self, test_db, product_barcode, db_conn):
        """Exactly at the minimum is not a trigger — only once stock drops
        below it (name of the function notwithstanding, this used to
        include the boundary case; deliberately changed)."""
        db_conn.execute(
            "UPDATE products SET reorder_point=10 WHERE barcode=?", (product_barcode,)
        )
        db_conn.commit()
        soh_model.adjust(product_barcode, 10, "RECEIPT", "", "", "admin")
        results = soh_model.get_below_reorder()
        barcodes = [r["barcode"] for r in results]
        assert product_barcode not in barcodes

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

    def test_product_with_zero_reorder_point_and_zero_stock_excluded(self, test_db, product_barcode):
        # reorder_point=0 means "no threshold configured". With a strict <
        # comparison, qty=0 and reorder_point=0 no longer satisfy 0 < 0, so
        # this correctly excludes it — previously the <= comparison here
        # (with no reorder_point > 0 guard, unlike the other reorder
        # queries) let it through by accident.
        soh_model.adjust(product_barcode, 0, "RECEIPT", "", "", "admin")
        results = soh_model.get_below_reorder()
        assert not any(r["barcode"] == product_barcode for r in results)


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


# ── record_pos_refund_atomic ───────────────────────────────────────────────────

def _sell(product_barcode, qty=3, line_total=10.50, reference='SALE-REF'):
    soh_model.record_pos_sale_atomic(
        reference, '2026-05-01', 'cashier',
        [{'barcode': product_barcode, 'qty': qty, 'line_total': line_total, 'description': 'Test'}],
    )


class TestRecordPosRefundAtomic:
    def test_happy_path_returns_true_and_increases_stock(
        self, test_db, product_barcode, db_conn
    ):
        _sell(product_barcode, qty=3, line_total=10.50)
        lines = [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50, 'description': 'Test'}]
        result = soh_model.record_pos_refund_atomic(
            'RFD-001', 'SALE-REF', '2026-05-02', 'cashier', lines
        )
        assert result is True
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        # -3 from the sale, +1 from the refund
        assert row["quantity"] == pytest.approx(-2.0)

    def test_duplicate_refund_reference_returns_false_and_does_not_double_refund(
        self, test_db, product_barcode, db_conn
    ):
        _sell(product_barcode, qty=3, line_total=10.50)
        lines = [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50}]
        soh_model.record_pos_refund_atomic('RFD-DUP', 'SALE-REF', '2026-05-02', 'cashier', lines)
        result = soh_model.record_pos_refund_atomic(
            'RFD-DUP', 'SALE-REF', '2026-05-02', 'cashier', lines
        )
        assert result is False
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        # Only the first attempt's +1 applied, not +2
        assert row["quantity"] == pytest.approx(-2.0)

    def test_unknown_original_reference_raises(self, test_db, product_barcode):
        lines = [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50}]
        with pytest.raises(ValueError, match="never recorded as a sale"):
            soh_model.record_pos_refund_atomic(
                'RFD-BAD', 'NO-SUCH-SALE', '2026-05-02', 'cashier', lines
            )

    def test_refund_exceeding_sold_qty_raises_and_rolls_back(
        self, test_db, product_barcode, db_conn
    ):
        _sell(product_barcode, qty=3, line_total=10.50)
        lines = [{'barcode': product_barcode, 'qty': 5, 'line_total': 17.50}]
        with pytest.raises(ValueError, match="exceeds remaining refundable"):
            soh_model.record_pos_refund_atomic(
                'RFD-OVER', 'SALE-REF', '2026-05-02', 'cashier', lines
            )
        # Nothing should have been applied — stock still reflects only the sale.
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        assert row["quantity"] == pytest.approx(-3.0)
        refund_rows = db_conn.execute("SELECT * FROM pos_refunds WHERE reference='RFD-OVER'").fetchall()
        assert refund_rows == []

    def test_second_partial_refund_cannot_exceed_remaining_after_first(
        self, test_db, product_barcode, db_conn
    ):
        _sell(product_barcode, qty=3, line_total=10.50)
        soh_model.record_pos_refund_atomic(
            'RFD-1', 'SALE-REF', '2026-05-02', 'cashier',
            [{'barcode': product_barcode, 'qty': 2, 'line_total': 7.00}],
        )
        # Only 1 remains refundable — asking for 2 more must fail.
        with pytest.raises(ValueError, match="exceeds remaining refundable"):
            soh_model.record_pos_refund_atomic(
                'RFD-2', 'SALE-REF', '2026-05-02', 'cashier',
                [{'barcode': product_barcode, 'qty': 2, 'line_total': 7.00}],
            )
        # But exactly the remaining 1 is fine.
        result = soh_model.record_pos_refund_atomic(
            'RFD-3', 'SALE-REF', '2026-05-02', 'cashier',
            [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50}],
        )
        assert result is True

    def test_refund_records_return_movement(self, test_db, product_barcode, db_conn):
        _sell(product_barcode, qty=3, line_total=10.50)
        soh_model.record_pos_refund_atomic(
            'RFD-MOV', 'SALE-REF', '2026-05-02', 'cashier',
            [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50, 'description': 'Test Product'}],
        )
        row = db_conn.execute(
            "SELECT * FROM stock_movements WHERE reference='RFD-MOV'"
        ).fetchone()
        assert row is not None
        assert row["movement_type"] == "RETURN"
        assert row["quantity"] == pytest.approx(1.0)
        # notes holds the item description, same convention as a SALE movement
        # (the receipt viewer reads notes-or-description as the product name)
        # — the link back to the original sale lives on pos_refunds.original_reference.
        assert row["notes"] == "Test Product"

    def test_refund_original_reference_recoverable_via_pos_refunds(
        self, test_db, product_barcode, db_conn
    ):
        _sell(product_barcode, qty=3, line_total=10.50)
        soh_model.record_pos_refund_atomic(
            'RFD-MOV2', 'SALE-REF', '2026-05-02', 'cashier',
            [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50}],
        )
        header = soh_model.get_refund_header('RFD-MOV2')
        assert header is not None
        assert header['original_reference'] == 'SALE-REF'

    def test_refund_decreases_sales_daily(self, test_db, product_barcode, db_conn):
        _sell(product_barcode, qty=3, line_total=10.50)
        before = db_conn.execute(
            "SELECT quantity, sales_dollars FROM sales_daily WHERE plu=?", (product_barcode,)
        ).fetchone()
        soh_model.record_pos_refund_atomic(
            'RFD-SD', 'SALE-REF', '2026-05-01', 'cashier',
            [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50}],
        )
        after = db_conn.execute(
            "SELECT quantity, sales_dollars FROM sales_daily WHERE plu=?", (product_barcode,)
        ).fetchone()
        assert after["quantity"] == pytest.approx(before["quantity"] - 1)
        assert after["sales_dollars"] == pytest.approx(before["sales_dollars"] - 3.50)

    def test_selling_unit_refund_uses_master_barcode(
        self, test_db, product_barcode, db_conn
    ):
        su_bc = '9300000099888'
        db_conn.execute("""
            INSERT INTO product_selling_units
                (master_barcode, barcode, label, unit_qty, sell_price, active)
            VALUES (?, ?, '2-pack', 2, 7.00, 1)
        """, (product_barcode, su_bc))
        db_conn.commit()
        soh_model.record_pos_sale_atomic(
            'SALE-SU', '2026-05-01', 'cashier',
            [{'barcode': su_bc, 'qty': 1, 'line_total': 7.00, 'description': '2-pack'}],
        )
        soh_model.record_pos_refund_atomic(
            'RFD-SU', 'SALE-SU', '2026-05-02', 'cashier',
            [{'barcode': su_bc, 'qty': 1, 'line_total': 7.00}],
        )
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        # -2 from the sale (1 selling unit = 2 master units), +2 from the refund
        assert row["quantity"] == pytest.approx(0.0)

    def test_invalid_refund_date_raises(self, test_db, product_barcode):
        _sell(product_barcode)
        with pytest.raises(ValueError, match="refund_date"):
            soh_model.record_pos_refund_atomic(
                'RFD-BADDATE', 'SALE-REF', 'not-a-date', 'cashier',
                [{'barcode': product_barcode, 'qty': 1, 'line_total': 3.50}],
            )
