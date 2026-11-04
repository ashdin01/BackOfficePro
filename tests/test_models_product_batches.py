"""Tests for models/product_batches.py."""
from datetime import date, timedelta

import models.product_batches as batches_model


def _iso(days_from_today):
    return (date.today() + timedelta(days=days_from_today)).isoformat()


class TestAddBatch:
    def test_add_batch_returns_id(self, test_db, product_barcode):
        bid = batches_model.add_batch(product_barcode, _iso(3), 24)
        assert isinstance(bid, int) and bid > 0

    def test_add_batch_defaults_received_date_to_today(self, test_db, product_barcode):
        batches_model.add_batch(product_barcode, _iso(3), 24)
        [batch] = batches_model.get_expiring_batches(days=30)
        assert batch["received_date"] == date.today().isoformat()


class TestGetExpiringBatches:
    def test_includes_batch_within_window(self, test_db, product_barcode):
        batches_model.add_batch(product_barcode, _iso(2), 10)
        results = batches_model.get_expiring_batches(days=5)
        assert len(results) == 1
        assert results[0]["description"] == "Test Product"
        assert results[0]["qty_received"] == 10

    def test_excludes_batch_outside_window(self, test_db, product_barcode):
        batches_model.add_batch(product_barcode, _iso(30), 10)
        results = batches_model.get_expiring_batches(days=5)
        assert results == []

    def test_includes_already_overdue_batch(self, test_db, product_barcode):
        batches_model.add_batch(product_barcode, _iso(-2), 10)
        results = batches_model.get_expiring_batches(days=5)
        assert len(results) == 1

    def test_excludes_resolved_batch(self, test_db, product_barcode):
        bid = batches_model.add_batch(product_barcode, _iso(2), 10)
        batches_model.mark_resolved(bid)
        assert batches_model.get_expiring_batches(days=5) == []

    def test_orders_soonest_first(self, test_db, product_barcode):
        batches_model.add_batch(product_barcode, _iso(4), 1)
        batches_model.add_batch(product_barcode, _iso(1), 2)
        results = batches_model.get_expiring_batches(days=10)
        assert [r["qty_received"] for r in results] == [2, 1]

    def test_defaults_to_batch_expiry_warning_window(self, test_db, product_barcode):
        from config.constants import BATCH_EXPIRY_WARNING_DAYS
        batches_model.add_batch(product_barcode, _iso(BATCH_EXPIRY_WARNING_DAYS - 1), 5)
        batches_model.add_batch(product_barcode, _iso(BATCH_EXPIRY_WARNING_DAYS + 5), 5)
        results = batches_model.get_expiring_batches()
        assert len(results) == 1


class TestMarkResolved:
    def test_mark_resolved_removes_from_expiring_list(self, test_db, product_barcode):
        bid = batches_model.add_batch(product_barcode, _iso(1), 10)
        assert len(batches_model.get_expiring_batches(days=5)) == 1
        batches_model.mark_resolved(bid)
        assert batches_model.get_expiring_batches(days=5) == []


class TestOutcomeCapture:
    def _row(self, db_conn, bid):
        return db_conn.execute("SELECT * FROM product_batches WHERE id=?", (bid,)).fetchone()

    def test_mark_resolved_records_outcome_and_qty(self, test_db, product_barcode, db_conn):
        bid = batches_model.add_batch(product_barcode, _iso(1), 24)
        batches_model.mark_resolved(bid, "WRITTEN_OFF", 5)
        r = self._row(db_conn, bid)
        assert (r["resolved"], r["outcome"], r["qty_remaining"]) == (1, "WRITTEN_OFF", 5)
        assert r["resolved_at"] is not None

    def test_mark_resolved_without_outcome_still_works(self, test_db, product_barcode, db_conn):
        bid = batches_model.add_batch(product_barcode, _iso(1), 24)
        batches_model.mark_resolved(bid)
        r = self._row(db_conn, bid)
        assert r["resolved"] == 1 and r["outcome"] is None


class TestReversalKeepsBatches:
    def test_reverse_marks_open_batches_reversed_and_keeps_handled_ones(
        self, test_db, supplier_id, product_barcode, db_conn
    ):
        import models.purchase_order as po_model
        import controllers.purchase_order_controller as po_ctrl
        import models.po_lines as lines_model
        po_id = po_ctrl.create_po(supplier_id, delivery_date="2026-07-01")
        po_ctrl.update_po_status(po_id, "SENT")
        lines_model.add(po_id, product_barcode, "Test Product", 10, 2.50, "", 6)
        line = lines_model.get_by_po(po_id)[0]
        po = po_model.get_by_id(po_id)
        po_ctrl.receive_po_atomic(po_id, po["po_number"], [{
            "line_id": line["id"], "barcode": product_barcode, "new_received_qty": 10,
            "new_received_weight": 0, "actual_cost": None, "unit_cost": None,
            "is_promo": False, "qty_units": 60, "use_by_date": _iso(3)}], "RECEIVED")
        handled = batches_model.add_batch(product_barcode, _iso(2), 6, po_line_id=line["id"])
        batches_model.mark_resolved(handled, "SOLD_THROUGH", 0)

        po_ctrl.reverse_po(po_id)

        rows = {r["id"]: r for r in db_conn.execute("SELECT * FROM product_batches").fetchall()}
        assert len(rows) == 2                                  # nothing deleted
        assert rows[handled]["outcome"] == "SOLD_THROUGH"      # earlier outcome untouched
        reversed_row = next(r for i, r in rows.items() if i != handled)
        assert reversed_row["outcome"] == "REVERSED" and reversed_row["resolved"] == 1
        assert batches_model.get_expiring_batches(days=9999) == []
