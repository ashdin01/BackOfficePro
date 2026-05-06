"""Tests for models/stock_on_hand.py — stock adjustments and audit trail."""
import pytest
from database.connection import get_connection
import models.stock_on_hand as soh_model


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
