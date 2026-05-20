"""Tests for models/customer.py, models/ar_invoice.py, models/ar_payment.py."""
import pytest
import models.customer as customer_model
import models.ar_invoice as invoice_model
import models.ar_payment as payment_model


# ── Customers ─────────────────────────────────────────────────────────────────

class TestCustomer:
    def test_add_returns_id(self, test_db):
        cid = customer_model.add("ACME", "Acme Corp")
        assert isinstance(cid, int) and cid > 0

    def test_get_by_id(self, test_db):
        cid = customer_model.add("ACME", "Acme Corp")
        c = customer_model.get_by_id(cid)
        assert c["name"] == "Acme Corp"
        assert c["code"] == "ACME"

    def test_get_by_code(self, test_db):
        customer_model.add("ACME", "Acme Corp")
        c = customer_model.get_by_code("ACME")
        assert c is not None
        assert c["name"] == "Acme Corp"

    def test_add_with_active_false(self, test_db):
        cid = customer_model.add("INACT", "Inactive Co", active=0)
        c = customer_model.get_by_id(cid)
        assert c["active"] == 0

    def test_get_all_returns_active_only_by_default(self, test_db):
        customer_model.add("ACT", "Active Co", active=1)
        customer_model.add("INACT", "Inactive Co", active=0)
        rows = customer_model.get_all(active_only=True)
        codes = [r["code"] for r in rows]
        assert "ACT" in codes
        assert "INACT" not in codes

    def test_get_all_includes_inactive_when_requested(self, test_db):
        customer_model.add("ACT", "Active Co", active=1)
        customer_model.add("INACT", "Inactive Co", active=0)
        rows = customer_model.get_all(active_only=False)
        codes = [r["code"] for r in rows]
        assert "INACT" in codes

    def test_deactivate(self, test_db):
        cid = customer_model.add("ACME", "Acme Corp")
        customer_model.deactivate(cid)
        assert customer_model.get_by_id(cid)["active"] == 0

    def test_get_by_id_unknown_returns_none(self, test_db):
        assert customer_model.get_by_id(99999) is None

    def test_update_name(self, test_db):
        cid = customer_model.add("ACME", "Acme Corp")
        customer_model.update(cid, "ACME", "Acme Pty Ltd")
        assert customer_model.get_by_id(cid)["name"] == "Acme Pty Ltd"

    def test_default_payment_terms(self, test_db):
        cid = customer_model.add("ACME", "Acme Corp")
        assert customer_model.get_by_id(cid)["payment_terms_days"] == 37


# ── Invoice model ─────────────────────────────────────────────────────────────

class TestArInvoice:
    def test_create_returns_id(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        assert isinstance(inv_id, int) and inv_id > 0

    def test_get_by_id(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        inv = invoice_model.get_by_id(inv_id)
        assert inv["invoice_number"] == "INV-00001"
        assert inv["status"] == "DRAFT"

    def test_status_defaults_to_draft(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        assert invoice_model.get_by_id(inv_id)["status"] == "DRAFT"

    def test_update_status(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.update_status(inv_id, "SENT")
        assert invoice_model.get_by_id(inv_id)["status"] == "SENT"

    def test_add_line_updates_totals(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Milk 2L", 10, 2.00, gst_rate=10.0)
        inv = invoice_model.get_by_id(inv_id)
        assert inv["subtotal"] == pytest.approx(20.00)
        assert inv["gst_amount"] == pytest.approx(2.00)
        assert inv["total"] == pytest.approx(22.00)

    def test_add_gst_free_line(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Fresh Produce", 5, 3.00, gst_rate=0.0)
        inv = invoice_model.get_by_id(inv_id)
        assert inv["gst_amount"] == pytest.approx(0.00)
        assert inv["subtotal"] == pytest.approx(15.00)

    def test_add_line_with_discount(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Widget", 1, 100.00, discount_pct=10.0, gst_rate=10.0)
        lines = invoice_model.get_lines(inv_id)
        assert lines[0]["line_subtotal"] == pytest.approx(90.00)

    def test_delete_line_recalculates_totals(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Line A", 1, 10.00)
        invoice_model.add_line(inv_id, "Line B", 1, 20.00)
        line_b = invoice_model.get_lines(inv_id)[1]
        invoice_model.delete_line(line_b["id"])
        inv = invoice_model.get_by_id(inv_id)
        assert inv["subtotal"] == pytest.approx(10.00)

    def test_void_invoice(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.void_invoice(inv_id)
        assert invoice_model.get_by_id(inv_id)["status"] == "VOID"

    def test_amount_paid_starts_at_zero(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        assert invoice_model.get_by_id(inv_id)["amount_paid"] == pytest.approx(0.0)

    def test_get_all_filters_by_customer(self, test_db, customer_id):
        cid2 = customer_model.add("OTHER", "Other Co")
        invoice_model.create("INV-00001", customer_id, "2026-05-01", "2026-06-07")
        invoice_model.create("INV-00002", cid2, "2026-05-01", "2026-06-07")
        rows = invoice_model.get_all(customer_id=customer_id)
        assert all(r["customer_id"] == customer_id for r in rows)
        assert len(rows) == 1


# ── Invoice line calculation ──────────────────────────────────────────────────

class TestCalcLine:
    def test_basic_gst(self):
        sub, gst, total = invoice_model._calc_line(10, 2.00, 0, 10.0)
        assert sub   == pytest.approx(20.00)
        assert gst   == pytest.approx(2.00)
        assert total == pytest.approx(22.00)

    def test_gst_free(self):
        sub, gst, total = invoice_model._calc_line(5, 3.00, 0, 0.0)
        assert sub   == pytest.approx(15.00)
        assert gst   == pytest.approx(0.00)
        assert total == pytest.approx(15.00)

    def test_discount_applied_before_gst(self):
        sub, gst, total = invoice_model._calc_line(1, 100.00, 10.0, 10.0)
        assert sub   == pytest.approx(90.00)
        assert gst   == pytest.approx(9.00)
        assert total == pytest.approx(99.00)

    def test_zero_quantity(self):
        sub, gst, total = invoice_model._calc_line(0, 50.00, 0, 10.0)
        assert sub == pytest.approx(0.00)
        assert total == pytest.approx(0.00)


# ── Payments ──────────────────────────────────────────────────────────────────

class TestArPayment:
    def _make_invoice(self, customer_id, amount=110.00):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Goods", 1, amount / 1.1, gst_rate=10.0)
        invoice_model.update_status(inv_id, "SENT")
        return inv_id

    def test_add_payment_returns_id(self, test_db, customer_id):
        inv_id = self._make_invoice(customer_id)
        pid = payment_model.add(inv_id, customer_id, "2026-05-15", 110.00)
        assert isinstance(pid, int) and pid > 0

    def test_total_paid_reflects_payment(self, test_db, customer_id):
        inv_id = self._make_invoice(customer_id)
        payment_model.add(inv_id, customer_id, "2026-05-15", 50.00)
        assert payment_model.total_paid(inv_id) == pytest.approx(50.00)

    def test_total_paid_accumulates_multiple_payments(self, test_db, customer_id):
        inv_id = self._make_invoice(customer_id)
        payment_model.add(inv_id, customer_id, "2026-05-15", 50.00)
        payment_model.add(inv_id, customer_id, "2026-05-20", 60.00)
        assert payment_model.total_paid(inv_id) == pytest.approx(110.00)

    def test_total_paid_zero_for_no_payments(self, test_db, customer_id):
        inv_id = self._make_invoice(customer_id)
        assert payment_model.total_paid(inv_id) == pytest.approx(0.00)

    def test_get_by_invoice(self, test_db, customer_id):
        inv_id = self._make_invoice(customer_id)
        payment_model.add(inv_id, customer_id, "2026-05-15", 110.00)
        payments = payment_model.get_by_invoice(inv_id)
        assert len(payments) == 1
        assert payments[0]["amount"] == pytest.approx(110.00)
