"""Tests for models/purchase_order.py and models/po_lines.py."""
import pytest
from database.connection import get_connection
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.stock_on_hand as soh_model


# ── PO creation ───────────────────────────────────────────────────────────────

class TestPoCreate:
    def test_returns_integer_id(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        assert isinstance(po_id, int)
        assert po_id > 0

    def test_created_po_has_draft_status(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po = po_model.get_by_id(po_id)
        assert po["status"] == "DRAFT"

    def test_po_number_generated_and_not_empty(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po = po_model.get_by_id(po_id)
        assert po["po_number"] and len(po["po_number"]) > 0

    def test_po_numbers_are_unique(self, test_db, supplier_id):
        id1 = po_model.create(supplier_id, "2026-06-01", "", "admin")
        id2 = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po1 = po_model.get_by_id(id1)
        po2 = po_model.get_by_id(id2)
        assert po1["po_number"] != po2["po_number"]

    def test_get_by_id_returns_none_for_missing(self, test_db):
        assert po_model.get_by_id(99999) is None

    def test_supplier_name_included_in_get_by_id(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po = po_model.get_by_id(po_id)
        assert po["supplier_name"] == "Test Supplier"


# ── Status transitions ────────────────────────────────────────────────────────

class TestPoStatus:
    def test_update_status_to_sent(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po_model.update_status(po_id, "SENT")
        assert po_model.get_by_id(po_id)["status"] == "SENT"

    def test_update_status_to_received(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po_model.update_status(po_id, "RECEIVED")
        assert po_model.get_by_id(po_id)["status"] == "RECEIVED"

    def test_cancel_sets_cancelled_status(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po_model.cancel(po_id)
        assert po_model.get_by_id(po_id)["status"] == "CANCELLED"


# ── PO lines ──────────────────────────────────────────────────────────────────

class TestPoLines:
    def test_add_line_and_retrieve(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        lines = lines_model.get_by_po(po_id)
        assert len(lines) == 1
        assert lines[0]["barcode"] == product_barcode
        assert lines[0]["ordered_qty"] == 5
        assert lines[0]["unit_cost"] == pytest.approx(2.00)

    def test_multiple_lines_on_same_po(self, test_db, supplier_id, product_barcode, gst_free_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Taxable Product", 3, 2.00, "")
        lines_model.add(po_id, gst_free_barcode, "GST Free Product", 2, 1.50, "")
        lines = lines_model.get_by_po(po_id)
        assert len(lines) == 2

    def test_get_by_po_returns_empty_for_new_po(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        assert lines_model.get_by_po(po_id) == []

    def test_receive_updates_received_qty(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 10, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        lines_model.receive(line["id"], 8, 2.00)
        updated = lines_model.get_by_po(po_id)[0]
        assert updated["received_qty"] == 8

    def test_received_qty_starts_at_zero(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 10, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        assert line["received_qty"] == 0

    def test_correct_received_qty(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 10, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        lines_model.receive(line["id"], 8, 2.00)
        lines_model.correct_received(line["id"], 10)
        updated = lines_model.get_by_po(po_id)[0]
        assert updated["received_qty"] == 10

    def test_delete_line(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        lines_model.delete(line["id"])
        assert lines_model.get_by_po(po_id) == []


# ── PO reversal ───────────────────────────────────────────────────────────────

class TestPoReverse:
    def _setup_received_po(self, supplier_id, product_barcode):
        """Helper: create a RECEIVED PO with 5 units received, SOH adjusted."""
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        lines_model.receive(line["id"], 5, 2.00)
        soh_model.adjust(product_barcode, 5, "RECEIPT",
                         po_model.get_by_id(po_id)["po_number"], "", "admin")
        po_model.update_status(po_id, "RECEIVED")
        return po_id

    def test_reverse_sets_status_to_reversed(self, test_db, supplier_id, product_barcode):
        po_id = self._setup_received_po(supplier_id, product_barcode)
        po_model.reverse(po_id, "admin")
        assert po_model.get_by_id(po_id)["status"] == "REVERSED"

    def test_reverse_reduces_stock_by_received_qty(self, test_db, supplier_id, product_barcode):
        po_id = self._setup_received_po(supplier_id, product_barcode)
        before = soh_model.get_by_barcode(product_barcode)["quantity"]
        po_model.reverse(po_id, "admin")
        after = soh_model.get_by_barcode(product_barcode)["quantity"]
        assert after == before - 5

    def test_reverse_creates_reversal_movement(self, test_db, supplier_id, product_barcode):
        po_id = self._setup_received_po(supplier_id, product_barcode)
        po_model.reverse(po_id, "admin")
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=? AND movement_type='REVERSAL'",
            (product_barcode,)
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["quantity"] == -5

    def test_reverse_draft_po_raises(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        with pytest.raises(ValueError):
            po_model.reverse(po_id, "admin")

    def test_reverse_nonexistent_po_raises(self, test_db):
        with pytest.raises(ValueError):
            po_model.reverse(99999, "admin")
