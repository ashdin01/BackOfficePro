"""Tests for models/ar_invoice.py — comprehensive coverage."""
import pytest
from database.connection import get_connection
import models.ar_invoice as invoice_model
import controllers.ar_controller as ar_ctrl


# ── Local fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def invoice_id(test_db, customer_id):
    """Create a DRAFT invoice and return its id."""
    return invoice_model.create(
        "INV-TEST-01", customer_id, "2026-05-01", "2026-06-07"
    )


# ── TestCreate ────────────────────────────────────────────────────────────────

class TestCreate:
    def test_create_returns_positive_int(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        assert isinstance(inv_id, int)
        assert inv_id > 0

    def test_created_invoice_has_draft_status(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        inv = invoice_model.get_by_id(inv_id)
        assert inv["status"] == "DRAFT"

    def test_get_by_id_returns_customer_name(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        inv = invoice_model.get_by_id(inv_id)
        assert inv is not None
        assert "customer_name" in inv
        assert inv["customer_name"] == "Test Customer"

    def test_get_by_id_returns_none_for_unknown(self, test_db):
        assert invoice_model.get_by_id(99999) is None

    def test_get_all_returns_created_invoice(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        all_invoices = invoice_model.get_all()
        ids = [r["id"] for r in all_invoices]
        assert inv_id in ids

    def test_get_all_filters_by_customer_id(self, test_db, customer_id, db_conn):
        # Create a second customer
        db_conn.execute(
            "INSERT INTO customers (code, name, payment_terms_days) VALUES ('OTHER', 'Other Co', 37)"
        )
        db_conn.commit()
        other_id = db_conn.execute(
            "SELECT id FROM customers WHERE code='OTHER'"
        ).fetchone()["id"]

        inv_id = invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.create("INV-00002", other_id, "2026-05-01", "2026-06-07")

        rows = invoice_model.get_all(customer_id=customer_id)
        assert all(r["customer_id"] == customer_id for r in rows)
        assert len(rows) == 1

    def test_get_all_filters_by_status_draft_found(self, test_db, customer_id):
        invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        rows = invoice_model.get_all(status="DRAFT")
        assert len(rows) >= 1

    def test_get_all_filters_by_status_sent_excluded(self, test_db, customer_id):
        invoice_model.create(
            "INV-00001", customer_id, "2026-05-01", "2026-06-07"
        )
        rows = invoice_model.get_all(status="SENT")
        assert len(rows) == 0


# ── TestLines ─────────────────────────────────────────────────────────────────

class TestLines:
    def test_add_line_inserts_correct_fields(self, test_db, invoice_id):
        invoice_model.add_line(
            invoice_id, "Widget", 2, 5.00, barcode="9300000000001"
        )
        lines = invoice_model.get_lines(invoice_id)
        assert len(lines) == 1
        line = lines[0]
        assert line["barcode"] == "9300000000001"
        assert line["description"] == "Widget"
        assert line["quantity"] == 2
        assert line["unit_price"] == pytest.approx(5.00)

    def test_add_line_gst_calculation(self, test_db, invoice_id):
        # 1 unit @ $10.00 with 10% GST
        invoice_model.add_line(invoice_id, "Test Item", 1, 10.00, gst_rate=10.0)
        lines = invoice_model.get_lines(invoice_id)
        line = lines[0]
        assert line["line_subtotal"] == pytest.approx(10.00)
        assert line["line_gst"]      == pytest.approx(1.00)
        assert line["line_total"]    == pytest.approx(11.00)

    def test_add_line_triggers_update_totals(self, test_db, invoice_id):
        invoice_model.add_line(invoice_id, "Item A", 1, 10.00, gst_rate=10.0)
        inv = invoice_model.get_by_id(invoice_id)
        assert inv["total"] == pytest.approx(11.00)

    def test_two_lines_total_equals_sum_of_line_totals(self, test_db, invoice_id):
        invoice_model.add_line(invoice_id, "Item A", 1, 10.00, gst_rate=10.0)
        invoice_model.add_line(invoice_id, "Item B", 2, 5.00,  gst_rate=10.0)
        lines = invoice_model.get_lines(invoice_id)
        expected_total = sum(l["line_total"] for l in lines)
        inv = invoice_model.get_by_id(invoice_id)
        assert inv["total"] == pytest.approx(expected_total)

    def test_update_line_changes_qty_and_recalculates_total(self, test_db, invoice_id):
        invoice_model.add_line(invoice_id, "Widget", 1, 10.00, gst_rate=10.0)
        line = invoice_model.get_lines(invoice_id)[0]
        invoice_model.update_line(line["id"], "Widget", 3, 10.00, gst_rate=10.0)
        inv = invoice_model.get_by_id(invoice_id)
        # 3 × 10.00 × 1.10 = 33.00
        assert inv["total"] == pytest.approx(33.00)

    def test_delete_line_removes_it_and_zeroes_total(self, test_db, invoice_id):
        invoice_model.add_line(invoice_id, "Widget", 1, 10.00, gst_rate=10.0)
        line = invoice_model.get_lines(invoice_id)[0]
        invoice_model.delete_line(line["id"])
        assert invoice_model.get_lines(invoice_id) == []
        inv = invoice_model.get_by_id(invoice_id)
        assert inv["total"] == pytest.approx(0.00)

    def test_discount_pct_reduces_line_subtotal(self, test_db, invoice_id):
        # 10% discount on $10.00 → subtotal = $9.00
        invoice_model.add_line(
            invoice_id, "Discounted", 1, 10.00, discount_pct=10.0, gst_rate=10.0
        )
        line = invoice_model.get_lines(invoice_id)[0]
        assert line["line_subtotal"] == pytest.approx(9.00)

    def test_gst_rate_zero_gives_zero_gst(self, test_db, invoice_id):
        invoice_model.add_line(invoice_id, "GST Free", 1, 10.00, gst_rate=0.0)
        line = invoice_model.get_lines(invoice_id)[0]
        assert line["line_gst"] == pytest.approx(0.00)


# ── TestStatusAndNotes ────────────────────────────────────────────────────────

class TestStatusAndNotes:
    def test_update_status_changes_status(self, test_db, invoice_id):
        invoice_model.update_status(invoice_id, "SENT")
        assert invoice_model.get_by_id(invoice_id)["status"] == "SENT"

    def test_void_invoice_sets_void_status(self, test_db, invoice_id):
        invoice_model.void_invoice(invoice_id)
        assert invoice_model.get_by_id(invoice_id)["status"] == "VOID"

    def test_update_notes_persists(self, test_db, invoice_id):
        invoice_model.update_notes(invoice_id, "Please pay promptly.")
        assert invoice_model.get_by_id(invoice_id)["notes"] == "Please pay promptly."

    def test_update_amount_paid_persists(self, test_db, invoice_id):
        invoice_model._update_amount_paid(invoice_id, 55.00)
        assert invoice_model.get_by_id(invoice_id)["amount_paid"] == pytest.approx(55.00)


# ── TestRefreshOverdue ────────────────────────────────────────────────────────

class TestRefreshOverdue:
    def _make_invoice(self, customer_id, status, due_date):
        inv_id = invoice_model.create(
            f"INV-{status}", customer_id, "2026-01-01", due_date
        )
        if status in ('PAID', 'PARTIAL'):
            invoice_model.add_line(inv_id, "Item", 1, 100.00)
            amount = 110.00 if status == 'PAID' else 50.00
            invoice_model.apply_payment(inv_id, customer_id, "2026-01-01", amount)
        else:
            invoice_model.update_status(inv_id, status)
        return inv_id

    def test_sent_invoice_past_due_becomes_overdue(self, test_db, customer_id):
        inv_id = self._make_invoice(customer_id, "SENT", "2025-12-31")
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "OVERDUE"

    def test_draft_invoice_not_affected_by_refresh_overdue(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-DRAFT", customer_id, "2026-01-01", "2025-12-31"
        )
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "DRAFT"

    def test_paid_invoice_not_affected_by_refresh_overdue(self, test_db, customer_id):
        inv_id = self._make_invoice(customer_id, "PAID", "2025-12-31")
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "PAID"


# ── TestGetUnpaidForAgedDebtors ───────────────────────────────────────────────

class TestGetUnpaidForAgedDebtors:
    """get_aged_debtors() in ar_controller excludes PAID and VOID invoices."""

    def _make_invoice_with_status(self, customer_id, status, inv_num):
        inv_id = invoice_model.create(
            inv_num, customer_id, "2026-05-01", "2099-12-31"
        )
        invoice_model.add_line(inv_id, "Item", 1, 100.00, gst_rate=10.0)
        if status == "PAID":
            invoice_model.apply_payment(inv_id, customer_id, "2026-05-01", 110.00)
        elif status == "PARTIAL":
            invoice_model.apply_payment(inv_id, customer_id, "2026-05-01", 55.00)
        else:
            invoice_model.update_status(inv_id, status)
        return inv_id

    def test_draft_invoice_is_included_in_aged_debtors(self, test_db, customer_id):
        self._make_invoice_with_status(customer_id, "DRAFT", "INV-00001")
        debtors = ar_ctrl.get_aged_debtors()
        customer_ids = [d["customer_id"] for d in debtors]
        assert customer_id in customer_ids

    def test_paid_invoice_is_excluded_from_aged_debtors(self, test_db, customer_id):
        self._make_invoice_with_status(customer_id, "PAID", "INV-00002")
        debtors = ar_ctrl.get_aged_debtors()
        customer_ids = [d["customer_id"] for d in debtors]
        assert customer_id not in customer_ids

    def test_void_invoice_is_excluded_from_aged_debtors(self, test_db, customer_id):
        self._make_invoice_with_status(customer_id, "VOID", "INV-00003")
        debtors = ar_ctrl.get_aged_debtors()
        customer_ids = [d["customer_id"] for d in debtors]
        assert customer_id not in customer_ids


# ── TestGetStatementRows ──────────────────────────────────────────────────────

class TestGetStatementRows:
    def test_invoice_within_date_range_appears_in_result(
        self, test_db, customer_id, db_conn
    ):
        # Insert invoice directly via db_conn
        db_conn.execute("""
            INSERT INTO ar_invoices
                (invoice_number, customer_id, invoice_date, due_date, status,
                 subtotal, gst_amount, total)
            VALUES ('INV-STMT-01', ?, '2026-05-15', '2026-06-30', 'SENT',
                    100.0, 10.0, 110.0)
        """, (customer_id,))
        db_conn.commit()

        data = ar_ctrl.get_statement_data(customer_id, "2026-05-01", "2026-05-31")
        invoice_numbers = [i["invoice_number"] for i in data["invoices"]]
        assert "INV-STMT-01" in invoice_numbers

    def test_invoice_before_date_from_contributes_to_opening_balance(
        self, test_db, customer_id, db_conn
    ):
        # Invoice dated before date_from — should appear in opening balance
        db_conn.execute("""
            INSERT INTO ar_invoices
                (invoice_number, customer_id, invoice_date, due_date, status,
                 subtotal, gst_amount, total, amount_paid)
            VALUES ('INV-OLD-01', ?, '2026-03-01', '2026-04-30', 'SENT',
                    200.0, 20.0, 220.0, 0.0)
        """, (customer_id,))
        db_conn.commit()

        data = ar_ctrl.get_statement_data(customer_id, "2026-05-01", "2026-05-31")
        assert data["opening_balance"] == pytest.approx(220.0)
        # The old invoice should NOT appear in the invoices list
        invoice_numbers = [i["invoice_number"] for i in data["invoices"]]
        assert "INV-OLD-01" not in invoice_numbers
