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
