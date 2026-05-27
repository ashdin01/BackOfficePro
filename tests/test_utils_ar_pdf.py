"""Unit tests for utils/ar_pdf.py.

Both render functions accept plain dicts — no DB access required.
Tests verify that a valid PDF is written to the requested path.
"""
import os
import pytest
from utils.ar_pdf import render_invoice_pdf, render_statement_pdf


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def store_info():
    return {
        "store_name":    "Test Store",
        "store_address": "1 Main St",
        "store_phone":   "03 9000 0000",
        "store_abn":     "12 345 678 901",
    }


@pytest.fixture()
def invoice():
    return {
        "invoice_number": "INV-00001",
        "invoice_date":   "2026-05-01",
        "due_date":       "2026-06-07",
        "customer_name":  "ACME Pty Ltd",
        "address_line1":  "42 Trade St",
        "suburb":         "Melbourne",
        "state":          "VIC",
        "postcode":       "3000",
        "customer_abn":   "98 765 432 109",
        "subtotal":       100.00,
        "gst_amount":     10.00,
        "total":          110.00,
        "notes":          "",
    }


@pytest.fixture()
def lines():
    return [
        {
            "description": "Apples 1kg",
            "quantity":    10,
            "unit_price":  5.00,
            "discount_pct": 0,
            "line_gst":    5.00,
            "line_total":  55.00,
        },
        {
            "description": "Oranges 1kg",
            "quantity":    10,
            "unit_price":  5.00,
            "discount_pct": 0,
            "line_gst":    5.00,
            "line_total":  55.00,
        },
    ]


@pytest.fixture()
def customer():
    return {"name": "ACME Pty Ltd", "code": "ACME"}


@pytest.fixture()
def statement_data():
    return {
        "date_from":       "2026-01-01",
        "date_to":         "2026-05-31",
        "opening_balance": 0.0,
        "invoices": [
            {
                "invoice_date":   "2026-02-01",
                "invoice_number": "INV-00001",
                "total":          110.00,
            }
        ],
        "payments": [
            {
                "payment_date":   "2026-03-01",
                "invoice_number": "INV-00001",
                "amount":         110.00,
                "method":         "EFT",
            }
        ],
    }


# ── render_invoice_pdf ────────────────────────────────────────────────────────

class TestRenderInvoicePdf:
    def test_creates_file(self, tmp_path, invoice, lines, store_info):
        out = str(tmp_path / "inv.pdf")
        result = render_invoice_pdf(invoice, lines, store_info, out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_returns_output_path(self, tmp_path, invoice, lines, store_info):
        out = str(tmp_path / "inv.pdf")
        assert render_invoice_pdf(invoice, lines, store_info, out) == out

    def test_no_lines_still_creates_file(self, tmp_path, invoice, store_info):
        out = str(tmp_path / "empty.pdf")
        render_invoice_pdf(invoice, [], store_info, out)
        assert os.path.getsize(out) > 0

    def test_with_notes(self, tmp_path, invoice, lines, store_info):
        invoice["notes"] = "Handle with care"
        out = str(tmp_path / "notes.pdf")
        render_invoice_pdf(invoice, lines, store_info, out)
        assert os.path.exists(out)

    def test_with_discount_line(self, tmp_path, invoice, store_info):
        discounted = [{
            "description":  "Discounted Item",
            "quantity":     5,
            "unit_price":   10.00,
            "discount_pct": 10,
            "line_gst":     4.50,
            "line_total":   49.50,
        }]
        out = str(tmp_path / "discount.pdf")
        render_invoice_pdf(invoice, discounted, store_info, out)
        assert os.path.exists(out)

    def test_missing_optional_address_fields(self, tmp_path, lines, store_info):
        # invoice with no address_line1 / suburb / state / postcode / customer_abn
        inv = {
            "invoice_number": "INV-00099",
            "invoice_date":   "2026-05-01",
            "due_date":       "2026-06-07",
            "customer_name":  "Minimal Customer",
            "subtotal":       10.00,
            "gst_amount":     1.00,
            "total":          11.00,
            "notes":          "",
        }
        out = str(tmp_path / "minimal.pdf")
        render_invoice_pdf(inv, lines, store_info, out)
        assert os.path.exists(out)


# ── render_statement_pdf ──────────────────────────────────────────────────────

class TestRenderStatementPdf:
    def test_creates_file(self, tmp_path, customer, statement_data, store_info):
        out = str(tmp_path / "stmt.pdf")
        result = render_statement_pdf(customer, statement_data, store_info, out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_returns_output_path(self, tmp_path, customer, statement_data, store_info):
        out = str(tmp_path / "stmt.pdf")
        assert render_statement_pdf(customer, statement_data, store_info, out) == out

    def test_empty_statement(self, tmp_path, customer, store_info):
        data = {
            "date_from": "2026-01-01",
            "date_to":   "2026-05-31",
            "opening_balance": 0.0,
            "invoices":  [],
            "payments":  [],
        }
        out = str(tmp_path / "empty_stmt.pdf")
        render_statement_pdf(customer, data, store_info, out)
        assert os.path.getsize(out) > 0

    def test_nonzero_opening_balance_included(self, tmp_path, customer, store_info):
        data = {
            "date_from": "2026-03-01",
            "date_to":   "2026-05-31",
            "opening_balance": 250.00,
            "invoices":  [],
            "payments":  [],
        }
        out = str(tmp_path / "ob_stmt.pdf")
        render_statement_pdf(customer, data, store_info, out)
        assert os.path.exists(out)

    def test_multiple_invoices_and_payments(self, tmp_path, customer, store_info):
        data = {
            "date_from": "2026-01-01",
            "date_to":   "2026-06-30",
            "opening_balance": 0.0,
            "invoices": [
                {"invoice_date": "2026-02-01", "invoice_number": "INV-001", "total": 110.00},
                {"invoice_date": "2026-03-01", "invoice_number": "INV-002", "total": 220.00},
            ],
            "payments": [
                {"payment_date": "2026-02-15", "invoice_number": "INV-001", "amount": 110.00, "method": "EFT"},
            ],
        }
        out = str(tmp_path / "multi.pdf")
        render_statement_pdf(customer, data, store_info, out)
        assert os.path.exists(out)
