"""Tests for atomic PO operations and uncovered po_lines/controller functions."""
import pytest
from database.connection import get_connection
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.stock_on_hand as soh_model
import controllers.purchase_order_controller as po_ctrl
import config.constants as constants


# ── Local fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def po_id(test_db, supplier_id):
    """Create a DRAFT PO and return its id."""
    return po_model.create(supplier_id, "2026-06-01", "", "admin")


# ── TestReceiveAtomic ─────────────────────────────────────────────────────────

class TestReceiveAtomic:
    def _setup_line(self, po_id, product_barcode, ordered_qty=10, pack_qty=6):
        """Add a line and return the line dict."""
        lines_model.add(po_id, product_barcode, "Test Product",
                        ordered_qty, 2.00, "", pack_qty)
        return lines_model.get_by_po(po_id)[0]

    def _make_receipt(self, line_id, barcode, new_received_qty=10,
                      actual_cost=20.00, unit_cost=2.00,
                      is_promo=False, qty_units=60):
        return {
            "line_id":          line_id,
            "barcode":          barcode,
            "new_received_qty": new_received_qty,
            "actual_cost":      actual_cost,
            "unit_cost":        unit_cost,
            "is_promo":         is_promo,
            "qty_units":        qty_units,
        }

    def test_receive_atomic_updates_po_line_received_qty(
        self, test_db, po_id, product_barcode, supplier_id
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode,
                                     new_received_qty=10, qty_units=60)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [receipt], "RECEIVED")
        updated = lines_model.get_by_po(po_id)[0]
        assert updated["received_qty"] == 10

    def test_receive_atomic_increases_stock_on_hand(
        self, test_db, po_id, product_barcode
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode,
                                     new_received_qty=10, qty_units=60)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [receipt], "RECEIVED")
        soh = soh_model.get_by_barcode(product_barcode)
        assert soh is not None
        assert soh["quantity"] == pytest.approx(60)

    def test_receive_atomic_creates_receipt_movement(
        self, test_db, po_id, product_barcode
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode,
                                     new_received_qty=10, qty_units=60)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [receipt], "RECEIVED")
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=? AND movement_type=?",
            (product_barcode, constants.MOVE_RECEIPT),
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_receive_atomic_updates_cost_price_when_not_promo(
        self, test_db, po_id, product_barcode
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode,
                                     unit_cost=3.50, is_promo=False, qty_units=6)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [receipt], "RECEIVED")
        conn = get_connection()
        row = conn.execute(
            "SELECT cost_price FROM products WHERE barcode=?", (product_barcode,)
        ).fetchone()
        conn.close()
        assert row["cost_price"] == pytest.approx(3.50)

    def test_receive_atomic_does_not_update_cost_price_when_promo(
        self, test_db, po_id, product_barcode
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        # Original cost_price is 2.00 (from product_barcode fixture)
        receipt = self._make_receipt(line["id"], product_barcode,
                                     unit_cost=0.99, is_promo=True, qty_units=6)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [receipt], "RECEIVED")
        conn = get_connection()
        row = conn.execute(
            "SELECT cost_price FROM products WHERE barcode=?", (product_barcode,)
        ).fetchone()
        conn.close()
        # Cost should remain at original 2.00
        assert row["cost_price"] == pytest.approx(2.00)

    def test_receive_atomic_sets_po_status_to_final_status(
        self, test_db, po_id, product_barcode
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode, qty_units=6)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [receipt], "RECEIVED")
        assert po_model.get_by_id(po_id)["status"] == "RECEIVED"

    def test_receive_atomic_with_charges_inserts_po_charges(
        self, test_db, po_id, product_barcode
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode, qty_units=6)
        charges = [{"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 11.00}]
        po_ctrl.receive_po_atomic(
            po_id, po["po_number"], [receipt], "RECEIVED", charges=charges
        )
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM po_charges WHERE po_id=?", (po_id,)
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["description"] == "Freight"

    def test_receive_atomic_without_charges_leaves_po_charges_empty(
        self, test_db, po_id, product_barcode
    ):
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode, qty_units=6)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [receipt], "RECEIVED")
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM po_charges WHERE po_id=?", (po_id,)
        ).fetchall()
        conn.close()
        assert rows == []


# ── TestValidateCharges ───────────────────────────────────────────────────────

class TestValidateCharges:
    """_validate_charges must reject malformed dicts before any DB write."""

    def _good(self):
        return {"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 11.00}

    @pytest.mark.parametrize("bad_desc", ["", "   ", None])
    def test_rejects_bad_description(self, bad_desc):
        c = self._good()
        c['description'] = bad_desc
        with pytest.raises(ValueError, match="description"):
            po_model._validate_charges([c])

    @pytest.mark.parametrize("bad_rate", [-0.01, 100.01, "ten", None])
    def test_rejects_bad_tax_rate(self, bad_rate):
        c = self._good()
        c['tax_rate'] = bad_rate
        with pytest.raises(ValueError, match="tax_rate"):
            po_model._validate_charges([c])

    @pytest.mark.parametrize("bad_amt", [-0.01, -100.0, "abc", None])
    def test_rejects_bad_amount(self, bad_amt):
        c = self._good()
        c['amount_inc_tax'] = bad_amt
        with pytest.raises(ValueError, match="amount_inc_tax"):
            po_model._validate_charges([c])

    def test_rejects_missing_keys(self):
        with pytest.raises((ValueError, KeyError)):
            po_model._validate_charges([{"description": "Freight"}])

    def test_accepts_zero_amounts(self):
        po_model._validate_charges([
            {"description": "Freight", "tax_rate": 0.0, "amount_inc_tax": 0.0}
        ])

    def test_accepts_boundary_tax_rate(self):
        po_model._validate_charges([
            {"description": "Freight", "tax_rate": 100.0, "amount_inc_tax": 5.0}
        ])

    def test_receive_atomic_raises_before_db_write(
        self, test_db, po_id, product_barcode
    ):
        """Invalid charge must raise ValueError with no SOH change."""
        po = po_model.get_by_id(po_id)
        line = self._setup_line(po_id, product_barcode)
        receipt = self._make_receipt(line["id"], product_barcode, qty_units=6)
        bad_charges = [{"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": -5.0}]

        import models.stock_on_hand as soh_model
        soh_before = soh_model.get_by_barcode(product_barcode)

        with pytest.raises(ValueError, match="amount_inc_tax"):
            po_model.receive_atomic(
                po_id, po["po_number"], [receipt], "RECEIVED", charges=bad_charges
            )

        # SOH must be unchanged — validation raised before any DB write
        soh_after = soh_model.get_by_barcode(product_barcode)
        qty_before = soh_before["quantity"] if soh_before else 0
        qty_after  = soh_after["quantity"]  if soh_after  else 0
        assert qty_before == qty_after

    # reuse helpers from TestReceiveAtomic
    def _setup_line(self, po_id, product_barcode, ordered_qty=10, pack_qty=6):
        lines_model.add(po_id, product_barcode, "Test Product",
                        ordered_qty, 2.00, "", pack_qty)
        return lines_model.get_by_po(po_id)[0]

    def _make_receipt(self, line_id, barcode, new_received_qty=10,
                      actual_cost=20.00, unit_cost=2.00,
                      is_promo=False, qty_units=60):
        return {
            "line_id":          line_id,
            "barcode":          barcode,
            "new_received_qty": new_received_qty,
            "actual_cost":      actual_cost,
            "unit_cost":        unit_cost,
            "is_promo":         is_promo,
            "qty_units":        qty_units,
        }


# ── TestCloseForce ────────────────────────────────────────────────────────────

class TestCloseForce:
    def test_close_force_sets_unreceived_line_notes_to_not_supplied(
        self, test_db, po_id, product_barcode, supplier_id, gst_free_barcode
    ):
        # Add two lines: receive one, leave the other
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        lines_model.add(po_id, gst_free_barcode, "GST Free Product", 3, 1.50, "")
        all_lines = lines_model.get_by_po(po_id)
        received_line = all_lines[0]
        unreceived_line = all_lines[1]

        lines_model.receive(received_line["id"], 5, 2.00)
        po_ctrl.close_po_force(po_id, [unreceived_line["id"]], "out of stock")

        updated = lines_model.get_by_po(po_id)
        unreceived_updated = next(
            l for l in updated if l["id"] == unreceived_line["id"]
        )
        assert "NOT SUPPLIED" in (unreceived_updated["notes"] or "")

    def test_close_force_sets_po_status_to_received(
        self, test_db, po_id, product_barcode, gst_free_barcode
    ):
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        lines_model.add(po_id, gst_free_barcode, "GST Free Product", 3, 1.50, "")
        all_lines = lines_model.get_by_po(po_id)
        lines_model.receive(all_lines[0]["id"], 5, 2.00)

        po_ctrl.close_po_force(po_id, [all_lines[1]["id"]], "out of stock")
        assert po_model.get_by_id(po_id)["status"] == "RECEIVED"


# ── TestCloseCreditAtomic ─────────────────────────────────────────────────────

class TestCloseCreditAtomic:
    def _setup_soh(self, product_barcode, qty):
        soh_model.adjust(product_barcode, qty, "RECEIPT", "PO-SETUP", "", "admin")

    def test_close_credit_reduces_stock_on_hand(
        self, test_db, po_id, product_barcode
    ):
        self._setup_soh(product_barcode, 10)
        po = po_model.get_by_id(po_id)
        lines_model.add(po_id, product_barcode, "Test Product", 2, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        receipts = [{
            "line_id":        line["id"],
            "barcode":        product_barcode,
            "return_cartons": 2,
            "qty_units":      2,
        }]
        po_ctrl.close_credit_atomic(po_id, po["po_number"], receipts)
        soh = soh_model.get_by_barcode(product_barcode)
        assert soh["quantity"] == pytest.approx(8)

    def test_close_credit_creates_return_movement(
        self, test_db, po_id, product_barcode
    ):
        self._setup_soh(product_barcode, 10)
        po = po_model.get_by_id(po_id)
        lines_model.add(po_id, product_barcode, "Test Product", 2, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        receipts = [{
            "line_id":        line["id"],
            "barcode":        product_barcode,
            "return_cartons": 2,
            "qty_units":      2,
        }]
        po_ctrl.close_credit_atomic(po_id, po["po_number"], receipts)
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM stock_movements WHERE barcode=? AND movement_type='RETURN'",
            (product_barcode,),
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_close_credit_updates_po_line_received_qty(
        self, test_db, po_id, product_barcode
    ):
        self._setup_soh(product_barcode, 10)
        po = po_model.get_by_id(po_id)
        lines_model.add(po_id, product_barcode, "Test Product", 3, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        receipts = [{
            "line_id":        line["id"],
            "barcode":        product_barcode,
            "return_cartons": 3,
            "qty_units":      3,
        }]
        po_ctrl.close_credit_atomic(po_id, po["po_number"], receipts)
        updated = lines_model.get_by_po(po_id)[0]
        assert updated["received_qty"] == 3

    def test_close_credit_sets_po_status_to_closed(
        self, test_db, po_id, product_barcode
    ):
        self._setup_soh(product_barcode, 10)
        po = po_model.get_by_id(po_id)
        lines_model.add(po_id, product_barcode, "Test Product", 2, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        receipts = [{
            "line_id":        line["id"],
            "barcode":        product_barcode,
            "return_cartons": 2,
            "qty_units":      2,
        }]
        po_ctrl.close_credit_atomic(po_id, po["po_number"], receipts)
        assert po_model.get_by_id(po_id)["status"] == "CLOSED"


# ── TestGetWithSupplier ───────────────────────────────────────────────────────

class TestGetWithSupplier:
    def test_get_po_with_supplier_returns_supplier_name(
        self, test_db, po_id
    ):
        result = po_ctrl.get_po_with_supplier(po_id)
        assert result is not None
        assert result["supplier_name"] == "Test Supplier"

    def test_get_po_with_supplier_returns_none_for_missing(self, test_db):
        assert po_ctrl.get_po_with_supplier(99999) is None


# ── TestLinesUpdate ───────────────────────────────────────────────────────────

class TestLinesUpdate:
    def test_update_changes_ordered_qty_unit_cost_notes(
        self, test_db, po_id, product_barcode
    ):
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "original")
        line = lines_model.get_by_po(po_id)[0]
        lines_model.update(line["id"], ordered_qty=8, unit_cost=3.50, notes="updated")
        updated = lines_model.get_by_po(po_id)[0]
        assert updated["ordered_qty"] == 8
        assert updated["unit_cost"] == pytest.approx(3.50)
        assert updated["notes"] == "updated"


# ── TestRenumberSortOrder ─────────────────────────────────────────────────────

class TestRenumberSortOrder:
    def test_renumber_first_id_gets_sort_order_10(
        self, test_db, po_id, product_barcode, gst_free_barcode
    ):
        lines_model.add(po_id, product_barcode, "Product A", 5, 2.00, "")
        lines_model.add(po_id, gst_free_barcode, "Product B", 3, 1.50, "")
        all_lines = lines_model.get_by_po(po_id)
        # Renumber in reverse id order (second first, then first)
        ordered_ids = [all_lines[1]["id"], all_lines[0]["id"]]
        lines_model.renumber_sort_order(po_id, ordered_ids)

        conn = get_connection()
        row = conn.execute(
            "SELECT sort_order FROM po_lines WHERE id=?", (ordered_ids[0],)
        ).fetchone()
        conn.close()
        assert row["sort_order"] == 10

    def test_renumber_sort_order_increments_by_10(
        self, test_db, po_id, product_barcode, gst_free_barcode
    ):
        lines_model.add(po_id, product_barcode, "Product A", 5, 2.00, "")
        lines_model.add(po_id, gst_free_barcode, "Product B", 3, 1.50, "")
        all_lines = lines_model.get_by_po(po_id)
        ordered_ids = [l["id"] for l in all_lines]
        lines_model.renumber_sort_order(po_id, ordered_ids)

        conn = get_connection()
        rows = conn.execute(
            "SELECT id, sort_order FROM po_lines WHERE po_id=? ORDER BY sort_order",
            (po_id,),
        ).fetchall()
        conn.close()
        sort_orders = [r["sort_order"] for r in rows]
        assert sort_orders == [10, 20]


# ── TestGetReceivedCount ──────────────────────────────────────────────────────

class TestGetReceivedCount:
    def test_returns_zero_when_no_lines_received(
        self, test_db, po_id, product_barcode
    ):
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        assert lines_model.get_received_count(po_id) == 0

    def test_returns_one_when_one_line_received(
        self, test_db, po_id, product_barcode
    ):
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        lines_model.receive(line["id"], 5, 2.00)
        assert lines_model.get_received_count(po_id) == 1


# ── TestGetUnreceived ─────────────────────────────────────────────────────────

class TestGetUnreceived:
    def test_returns_lines_where_received_qty_less_than_ordered(
        self, test_db, po_id, product_barcode, gst_free_barcode
    ):
        lines_model.add(po_id, product_barcode, "Product A", 5, 2.00, "")
        lines_model.add(po_id, gst_free_barcode, "Product B", 3, 1.50, "")
        all_lines = lines_model.get_by_po(po_id)
        # Fully receive first line
        lines_model.receive(all_lines[0]["id"], 5, 2.00)

        unreceived = lines_model.get_unreceived(po_id)
        unreceived_ids = [r["id"] for r in unreceived]
        assert all_lines[1]["id"] in unreceived_ids
        assert all_lines[0]["id"] not in unreceived_ids

    def test_does_not_return_fully_received_lines(
        self, test_db, po_id, product_barcode
    ):
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00, "")
        line = lines_model.get_by_po(po_id)[0]
        lines_model.receive(line["id"], 5, 2.00)

        unreceived = lines_model.get_unreceived(po_id)
        assert unreceived == []


# ── TestGetOnOrderTotal ───────────────────────────────────────────────────────

class TestGetOnOrderTotal:
    def test_returns_zero_for_unknown_barcode(self, test_db):
        total = lines_model.get_on_order_total("0000000000000")
        assert total == 0

    def test_returns_units_outstanding_on_draft_po(
        self, test_db, po_id, product_barcode
    ):
        # product_barcode fixture has pack_qty=1; ordered_qty=10 → 10 units on order
        lines_model.add(po_id, product_barcode, "Test Product", 10, 2.00, "", pack_qty=1)
        total = lines_model.get_on_order_total(product_barcode)
        assert total == 10

    def test_returns_zero_after_po_is_received(
        self, test_db, po_id, product_barcode
    ):
        lines_model.add(po_id, product_barcode, "Test Product", 10, 2.00, "", pack_qty=1)
        po_model.update_status(po_id, "RECEIVED")
        total = lines_model.get_on_order_total(product_barcode)
        assert total == 0


# ── TestCleanupOldPos ─────────────────────────────────────────────────────────

class TestCleanupOldPos:
    def test_returns_count_of_deleted_pos(self, test_db, supplier_id):
        from datetime import datetime, timedelta
        old_ts = (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_connection()
        po_id = po_model.create(supplier_id, None, "", "admin")
        conn.execute(
            "UPDATE purchase_orders SET status='CANCELLED', updated_at=? WHERE id=?",
            (old_ts, po_id)
        )
        conn.commit()
        assert po_model.cleanup_old_pos() == 1

    def test_recent_cancelled_po_is_not_deleted(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, None, "", "admin")
        po_model.cancel(po_id)
        assert po_model.cleanup_old_pos() == 0
        assert po_model.get_by_id(po_id) is not None

    def test_raises_on_db_error(self, test_db, monkeypatch):
        """cleanup_old_pos must re-raise so callers can detect failure."""
        import sqlite3
        from unittest.mock import MagicMock
        from contextlib import contextmanager

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = sqlite3.OperationalError("simulated error")

        @contextmanager
        def mock_db_conn():
            yield mock_conn

        # Patch at the import site inside purchase_order, not in database.connection
        monkeypatch.setattr(po_model, "db_conn", mock_db_conn)

        with pytest.raises(sqlite3.OperationalError):
            po_model.cleanup_old_pos()
