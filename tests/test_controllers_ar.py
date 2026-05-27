"""Tests for controllers/ar_controller.py."""
import os
import pytest
from datetime import date
import models.customer as customer_model
import models.ar_invoice as invoice_model
import models.ar_payment as payment_model
import controllers.ar_controller as ar_ctrl


# ── calc_due_date ─────────────────────────────────────────────────────────────

class TestCalcDueDate:
    def test_returns_date_object(self):
        result = ar_ctrl.calc_due_date("2026-05-15")
        assert isinstance(result, date)

    def test_default_37_days_is_eom_plus_7(self):
        # May 2026: EOM = 31st, +7 = June 7
        result = ar_ctrl.calc_due_date("2026-05-15")
        assert result == date(2026, 6, 7)

    def test_eom_plus_7_for_end_of_month(self):
        # Invoice on last day of May — same EOM, +7 = June 7
        result = ar_ctrl.calc_due_date("2026-05-31")
        assert result == date(2026, 6, 7)

    def test_eom_plus_7_for_start_of_month(self):
        result = ar_ctrl.calc_due_date("2026-05-01")
        assert result == date(2026, 6, 7)

    def test_custom_terms_30_is_eom(self):
        # 30 days = EOM + 0 days
        result = ar_ctrl.calc_due_date("2026-05-15", payment_terms_days=30)
        assert result == date(2026, 5, 31)

    def test_custom_terms_37(self):
        result = ar_ctrl.calc_due_date("2026-01-15", payment_terms_days=37)
        # Jan EOM = 31, +7 = Feb 7
        assert result == date(2026, 2, 7)

    def test_accepts_date_object(self):
        result = ar_ctrl.calc_due_date(date(2026, 5, 15))
        assert result == date(2026, 6, 7)

    def test_february_leap_year(self):
        # 2028 is a leap year — Feb 29
        result = ar_ctrl.calc_due_date("2028-02-10", payment_terms_days=30)
        assert result == date(2028, 2, 29)

    def test_december_wraps_to_january(self):
        result = ar_ctrl.calc_due_date("2026-12-15", payment_terms_days=37)
        # Dec EOM = 31, +7 = Jan 7
        assert result == date(2027, 1, 7)


# ── create_invoice ────────────────────────────────────────────────────────────

class TestCreateInvoice:
    def test_returns_id_and_number(self, test_db, customer_id):
        inv_id, inv_num = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        assert isinstance(inv_id, int) and inv_id > 0
        assert inv_num.startswith("INV-")

    def test_invoice_number_is_sequential(self, test_db, customer_id):
        _, num1 = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        _, num2 = ar_ctrl.create_invoice(customer_id, "2026-05-16")
        seq1 = int(num1.split("-")[1])
        seq2 = int(num2.split("-")[1])
        assert seq2 == seq1 + 1

    def test_invoice_stored_with_draft_status(self, test_db, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        inv = invoice_model.get_by_id(inv_id)
        assert inv["status"] == "DRAFT"

    def test_due_date_calculated_from_customer_terms(self, test_db, customer_id):
        # customer_id fixture has payment_terms_days=37 → May EOM+7 = Jun 7
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        inv = invoice_model.get_by_id(inv_id)
        assert inv["due_date"] == "2026-06-07"

    def test_invalid_customer_raises(self, test_db):
        with pytest.raises(ValueError):
            ar_ctrl.create_invoice(99999, "2026-05-15")

    def test_notes_stored(self, test_db, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15", notes="Test note")
        assert invoice_model.get_by_id(inv_id)["notes"] == "Test note"

    def test_defaults_to_today(self, test_db, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id)
        inv = invoice_model.get_by_id(inv_id)
        assert inv["invoice_date"] == date.today().isoformat()


# ── record_payment ────────────────────────────────────────────────────────────

class TestRecordPayment:
    def _make_sent_invoice(self, customer_id, total=110.00):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-01")
        invoice_model.add_line(inv_id, "Goods", 1, total / 1.1, gst_rate=10.0)
        invoice_model.update_status(inv_id, "SENT")
        return inv_id

    def test_returns_payment_id(self, test_db, customer_id):
        inv_id = self._make_sent_invoice(customer_id)
        pid = ar_ctrl.record_payment(inv_id, 110.00, "2026-05-20")
        assert isinstance(pid, int) and pid > 0

    def test_full_payment_sets_status_paid(self, test_db, customer_id):
        inv_id = self._make_sent_invoice(customer_id)
        ar_ctrl.record_payment(inv_id, 110.00, "2026-05-20")
        assert invoice_model.get_by_id(inv_id)["status"] == "PAID"

    def test_partial_payment_sets_status_partial(self, test_db, customer_id):
        inv_id = self._make_sent_invoice(customer_id)
        ar_ctrl.record_payment(inv_id, 50.00, "2026-05-20")
        assert invoice_model.get_by_id(inv_id)["status"] == "PARTIAL"

    def test_amount_paid_updated_after_payment(self, test_db, customer_id):
        inv_id = self._make_sent_invoice(customer_id)
        ar_ctrl.record_payment(inv_id, 60.00, "2026-05-20")
        assert invoice_model.get_by_id(inv_id)["amount_paid"] == pytest.approx(60.00)

    def test_two_payments_accumulate_to_paid(self, test_db, customer_id):
        inv_id = self._make_sent_invoice(customer_id)
        ar_ctrl.record_payment(inv_id, 50.00, "2026-05-20")
        ar_ctrl.record_payment(inv_id, 60.00, "2026-05-21")
        assert invoice_model.get_by_id(inv_id)["status"] == "PAID"

    def test_invalid_invoice_raises(self, test_db):
        with pytest.raises(ValueError):
            ar_ctrl.record_payment(99999, 50.00, "2026-05-20")

    def test_payment_method_stored(self, test_db, customer_id):
        inv_id = self._make_sent_invoice(customer_id)
        ar_ctrl.record_payment(inv_id, 110.00, "2026-05-20", method="CASH")
        payments = payment_model.get_by_invoice(inv_id)
        assert payments[0]["method"] == "CASH"

    def test_reference_stored(self, test_db, customer_id):
        inv_id = self._make_sent_invoice(customer_id)
        ar_ctrl.record_payment(inv_id, 110.00, "2026-05-20", reference="REF-001")
        payments = payment_model.get_by_invoice(inv_id)
        assert payments[0]["reference"] == "REF-001"


# ── refresh_overdue_statuses ──────────────────────────────────────────────────

class TestRefreshOverdueStatuses:
    def test_past_due_sent_invoice_becomes_overdue(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-99001", customer_id, "2025-01-01", "2025-02-07"
        )
        invoice_model.update_status(inv_id, "SENT")
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "OVERDUE"

    def test_past_due_partial_invoice_becomes_overdue(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-99002", customer_id, "2025-01-01", "2025-02-07"
        )
        invoice_model.add_line(inv_id, "Goods", 1, 100.00, gst_rate=10.0)
        invoice_model.apply_payment(inv_id, customer_id, "2025-01-01", 50.00)
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "OVERDUE"

    def test_future_due_date_not_affected(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-99003", customer_id, "2026-05-01", "2027-12-31"
        )
        invoice_model.update_status(inv_id, "SENT")
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "SENT"

    def test_paid_invoice_not_touched(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-99004", customer_id, "2025-01-01", "2025-02-07"
        )
        invoice_model.add_line(inv_id, "Goods", 1, 100.00, gst_rate=10.0)
        invoice_model.apply_payment(inv_id, customer_id, "2025-01-01", 110.00)
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "PAID"

    def test_void_invoice_not_touched(self, test_db, customer_id):
        inv_id = invoice_model.create(
            "INV-99005", customer_id, "2025-01-01", "2025-02-07"
        )
        invoice_model.update_status(inv_id, "VOID")
        ar_ctrl.refresh_overdue_statuses()
        assert invoice_model.get_by_id(inv_id)["status"] == "VOID"


# ── get_aged_debtors ──────────────────────────────────────────────────────────

class TestGetAgedDebtors:
    def _make_invoice_with_balance(self, customer_id, inv_num, due_date, total=110.00):
        inv_id = invoice_model.create(
            inv_num, customer_id, "2026-05-01", due_date
        )
        invoice_model.add_line(inv_id, "Goods", 1, total / 1.1, gst_rate=10.0)
        invoice_model.update_status(inv_id, "SENT")
        return inv_id

    def test_current_invoice_in_current_bucket(self, test_db, customer_id):
        self._make_invoice_with_balance(customer_id, "INV-A001", "2027-12-31")
        result = ar_ctrl.get_aged_debtors("2026-05-15")
        assert len(result) == 1
        assert result[0]["current"] == pytest.approx(110.00)
        assert result[0]["days_30"] == pytest.approx(0.00)

    def test_overdue_30_days_in_30_bucket(self, test_db, customer_id):
        self._make_invoice_with_balance(customer_id, "INV-A002", "2026-04-15")
        result = ar_ctrl.get_aged_debtors("2026-05-15")
        assert result[0]["days_30"] == pytest.approx(110.00)

    def test_overdue_45_days_in_60_bucket(self, test_db, customer_id):
        # 45 days overdue: due 2026-03-31, as-of 2026-05-15
        self._make_invoice_with_balance(customer_id, "INV-A003", "2026-03-31")
        result = ar_ctrl.get_aged_debtors("2026-05-15")
        assert result[0]["days_60"] == pytest.approx(110.00)

    def test_overdue_90_plus_days(self, test_db, customer_id):
        self._make_invoice_with_balance(customer_id, "INV-A004", "2026-01-01")
        result = ar_ctrl.get_aged_debtors("2026-05-15")
        assert result[0]["days_90plus"] == pytest.approx(110.00)

    def test_paid_invoice_excluded(self, test_db, customer_id):
        inv_id = self._make_invoice_with_balance(customer_id, "INV-A005", "2026-04-15")
        invoice_model.apply_payment(inv_id, customer_id, "2026-04-15", 110.00)
        result = ar_ctrl.get_aged_debtors("2026-05-15")
        assert result == []

    def test_void_invoice_excluded(self, test_db, customer_id):
        inv_id = self._make_invoice_with_balance(customer_id, "INV-A006", "2026-04-15")
        invoice_model.update_status(inv_id, "VOID")
        result = ar_ctrl.get_aged_debtors("2026-05-15")
        assert result == []

    def test_total_matches_sum_of_buckets(self, test_db, customer_id):
        self._make_invoice_with_balance(customer_id, "INV-A007", "2026-04-15")
        result = ar_ctrl.get_aged_debtors("2026-05-15")
        row = result[0]
        bucket_sum = row["current"] + row["days_30"] + row["days_60"] + row["days_90plus"]
        assert bucket_sum == pytest.approx(row["total"])


# ── Invoice line management ───────────────────────────────────────────────────

class TestInvoiceLines:
    def _make_draft(self, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        return inv_id

    def test_add_line_appears_in_get_lines(self, test_db, customer_id):
        inv_id = self._make_draft(customer_id)
        ar_ctrl.add_invoice_line(inv_id, "Apples", 10, 1.50)
        lines = ar_ctrl.get_invoice_lines(inv_id)
        assert len(lines) == 1
        assert lines[0]["description"] == "Apples"

    def test_add_line_updates_invoice_total(self, test_db, customer_id):
        inv_id = self._make_draft(customer_id)
        ar_ctrl.add_invoice_line(inv_id, "Apples", 10, 1.00, gst_rate=10.0)
        inv = ar_ctrl.get_invoice_by_id(inv_id)
        assert inv["subtotal"] == pytest.approx(10.00)
        assert inv["gst_amount"] == pytest.approx(1.00)
        assert inv["total"] == pytest.approx(11.00)

    def test_update_line_changes_values(self, test_db, customer_id):
        inv_id = self._make_draft(customer_id)
        ar_ctrl.add_invoice_line(inv_id, "Apples", 10, 1.00)
        line_id = ar_ctrl.get_invoice_lines(inv_id)[0]["id"]
        ar_ctrl.update_invoice_line(line_id, "Oranges", 5, 2.00)
        lines = ar_ctrl.get_invoice_lines(inv_id)
        assert lines[0]["description"] == "Oranges"
        assert lines[0]["quantity"] == pytest.approx(5.0)

    def test_delete_line_removes_it(self, test_db, customer_id):
        inv_id = self._make_draft(customer_id)
        ar_ctrl.add_invoice_line(inv_id, "Apples", 10, 1.00)
        line_id = ar_ctrl.get_invoice_lines(inv_id)[0]["id"]
        ar_ctrl.delete_invoice_line(line_id)
        assert ar_ctrl.get_invoice_lines(inv_id) == []

    def test_multiple_lines_accumulate_total(self, test_db, customer_id):
        inv_id = self._make_draft(customer_id)
        ar_ctrl.add_invoice_line(inv_id, "A", 1, 10.00, gst_rate=10.0)
        ar_ctrl.add_invoice_line(inv_id, "B", 1, 20.00, gst_rate=10.0)
        inv = ar_ctrl.get_invoice_by_id(inv_id)
        assert inv["subtotal"] == pytest.approx(30.00)


# ── Invoice query wrappers ────────────────────────────────────────────────────

class TestInvoiceQueries:
    def test_get_invoice_by_id_returns_dict(self, test_db, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        inv = ar_ctrl.get_invoice_by_id(inv_id)
        assert isinstance(inv, dict)
        assert inv["id"] == inv_id

    def test_get_invoice_by_id_unknown_returns_none(self, test_db):
        assert ar_ctrl.get_invoice_by_id(99999) is None

    def test_get_all_invoices_returns_list(self, test_db, customer_id):
        ar_ctrl.create_invoice(customer_id, "2026-05-15")
        result = ar_ctrl.get_all_invoices()
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_get_all_invoices_filtered_by_customer(self, test_db, customer_id):
        ar_ctrl.create_invoice(customer_id, "2026-05-15")
        result = ar_ctrl.get_all_invoices(customer_id=customer_id)
        assert all(r["customer_id"] == customer_id for r in result)

    def test_get_all_invoices_filtered_by_status(self, test_db, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        ar_ctrl.update_invoice_status(inv_id, "SENT")
        drafts = ar_ctrl.get_all_invoices(status="DRAFT")
        assert all(r["status"] == "DRAFT" for r in drafts)

    def test_get_all_invoices_limit(self, test_db, customer_id):
        for _ in range(5):
            ar_ctrl.create_invoice(customer_id, "2026-05-15")
        result = ar_ctrl.get_all_invoices(limit=3)
        assert len(result) == 3

    def test_get_all_invoices_offset(self, test_db, customer_id):
        for _ in range(5):
            ar_ctrl.create_invoice(customer_id, "2026-05-15")
        all_rows   = ar_ctrl.get_all_invoices()
        page2_rows = ar_ctrl.get_all_invoices(limit=2, offset=2)
        assert page2_rows[0]["id"] == all_rows[2]["id"]

    def test_count_invoices(self, test_db, customer_id):
        for _ in range(3):
            ar_ctrl.create_invoice(customer_id, "2026-05-15")
        assert ar_ctrl.count_invoices(customer_id=customer_id) == 3

    def test_update_invoice_notes(self, test_db, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        ar_ctrl.update_invoice_notes(inv_id, "Special delivery")
        assert ar_ctrl.get_invoice_by_id(inv_id)["notes"] == "Special delivery"


# ── Customer management ───────────────────────────────────────────────────────

class TestCustomerManagement:
    def test_create_customer_returns_int(self, test_db):
        cid = ar_ctrl.create_customer("NEW001", "New Customer")
        assert isinstance(cid, int) and cid > 0

    def test_get_customer_by_id_returns_dict(self, test_db, customer_id):
        c = ar_ctrl.get_customer_by_id(customer_id)
        assert isinstance(c, dict)
        assert c["code"] == "CUST001"

    def test_get_customer_by_id_unknown_returns_none(self, test_db):
        assert ar_ctrl.get_customer_by_id(99999) is None

    def test_get_all_customers_returns_list(self, test_db, customer_id):
        result = ar_ctrl.get_all_customers()
        assert isinstance(result, list)
        assert any(c["id"] == customer_id for c in result)

    def test_get_all_customers_limit(self, test_db):
        for i in range(5):
            ar_ctrl.create_customer(f"C{i:03d}", f"Customer {i}")
        result = ar_ctrl.get_all_customers(limit=2)
        assert len(result) == 2

    def test_get_all_customers_offset(self, test_db):
        for i in range(5):
            ar_ctrl.create_customer(f"D{i:03d}", f"Delta {i}")
        all_rows   = ar_ctrl.get_all_customers()
        page2_rows = ar_ctrl.get_all_customers(limit=2, offset=2)
        assert page2_rows[0]["id"] == all_rows[2]["id"]

    def test_count_customers(self, test_db):
        for i in range(4):
            ar_ctrl.create_customer(f"E{i:03d}", f"Echo {i}")
        assert ar_ctrl.count_customers() >= 4

    def test_update_customer_persists_changes(self, test_db, customer_id):
        ar_ctrl.update_customer(customer_id, "CUST001", "Updated Name")
        c = ar_ctrl.get_customer_by_id(customer_id)
        assert c["name"] == "Updated Name"


# ── get_statement_data ────────────────────────────────────────────────────────

class TestGetStatementData:
    def test_returns_dict_with_required_keys(self, test_db, customer_id):
        data = ar_ctrl.get_statement_data(customer_id, "2026-01-01", "2026-12-31")
        assert "invoices" in data
        assert "payments" in data
        assert "opening_balance" in data

    def test_empty_range_has_zero_opening_balance(self, test_db, customer_id):
        data = ar_ctrl.get_statement_data(customer_id, "2026-01-01", "2026-12-31")
        assert data["opening_balance"] == pytest.approx(0.0)

    def test_sent_invoice_appears_in_statement(self, test_db, customer_id):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-06-01")
        invoice_model.add_line(inv_id, "Goods", 1, 100.00, gst_rate=10.0)
        invoice_model.update_status(inv_id, "SENT")
        data = ar_ctrl.get_statement_data(customer_id, "2026-01-01", "2026-12-31")
        assert len(data["invoices"]) == 1


# ── create_credit_note ────────────────────────────────────────────────────────

class TestCreateCreditNote:
    def test_returns_tuple_of_id_and_number(self, test_db, customer_id):
        result = ar_ctrl.create_credit_note(customer_id, reason="Return")
        cn_id, cn_num = result
        assert isinstance(cn_id, int) and cn_id > 0
        assert isinstance(cn_num, str)

    def test_credit_note_number_starts_with_cn(self, test_db, customer_id):
        cn_id, cn_num = ar_ctrl.create_credit_note(customer_id, reason="Overcharge")
        assert cn_num.startswith("CN-")

    def test_sequential_credit_note_numbers(self, test_db, customer_id):
        _, cn_num1 = ar_ctrl.create_credit_note(customer_id)
        _, cn_num2 = ar_ctrl.create_credit_note(customer_id)
        seq1 = int(cn_num1.split("-")[1])
        seq2 = int(cn_num2.split("-")[1])
        assert seq2 == seq1 + 1


# ── generate_invoice_pdf ──────────────────────────────────────────────────────

class TestGenerateInvoicePdf:
    def test_creates_file(self, test_db, customer_id, tmp_path):
        inv_id, _ = ar_ctrl.create_invoice(customer_id, "2026-05-15")
        invoice_model.add_line(inv_id, "Goods", 2, 10.00, gst_rate=10.0)
        out = str(tmp_path / "inv.pdf")
        result = ar_ctrl.generate_invoice_pdf(inv_id, output_path=out)
        assert result == out
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_unknown_invoice_raises(self, test_db):
        with pytest.raises(ValueError):
            ar_ctrl.generate_invoice_pdf(99999, output_path="/tmp/nope.pdf")


# ── generate_statement_pdf ────────────────────────────────────────────────────

class TestGenerateStatementPdf:
    def test_creates_file(self, test_db, customer_id, tmp_path):
        out = str(tmp_path / "stmt.pdf")
        result = ar_ctrl.generate_statement_pdf(
            customer_id, "2026-01-01", "2026-12-31", output_path=out
        )
        assert result == out
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_unknown_customer_raises(self, test_db):
        with pytest.raises(ValueError):
            ar_ctrl.generate_statement_pdf(99999, "2026-01-01", "2026-12-31", output_path="/tmp/nope.pdf")
