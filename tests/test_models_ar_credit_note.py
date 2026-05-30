"""Tests for models/ar_credit_note.py."""
import pytest
import models.ar_credit_note as cn_model
import models.ar_invoice as inv_model


@pytest.fixture()
def invoice_id(db_conn, customer_id):
    """Insert a minimal AR invoice and return its id."""
    from datetime import date
    today = date.today().isoformat()
    inv_model.create(
        invoice_number="INV-TEST-001",
        customer_id=customer_id,
        invoice_date=today,
        due_date=today,
        notes="",
        created_by="test",
    )
    row = db_conn.execute(
        "SELECT id FROM ar_invoices WHERE invoice_number='INV-TEST-001'"
    ).fetchone()
    return row["id"]


class TestGetById:
    def test_returns_none_for_missing_id(self, test_db):
        assert cn_model.get_by_id(9999) is None

    def test_returns_dict_for_existing_credit_note(self, invoice_id, customer_id):
        cn_id, _ = cn_model.create("CN-001", customer_id, invoice_id, "2026-01-15", "Damaged goods")
        result = cn_model.get_by_id(cn_id)
        assert result is not None
        assert isinstance(result, dict)
        assert result["credit_note_number"] == "CN-001"
        assert result["reason"] == "Damaged goods"


class TestCreate:
    def test_create_returns_id_and_number(self, invoice_id, customer_id):
        cn_id, number = cn_model.create("CN-002", customer_id, invoice_id, "2026-02-01", "Short ship")
        assert cn_id > 0
        assert number == "CN-002"

    def test_created_row_has_correct_fields(self, invoice_id, customer_id):
        cn_id, _ = cn_model.create("CN-003", customer_id, invoice_id, "2026-03-10", "Price error")
        row = cn_model.get_by_id(cn_id)
        assert row["customer_id"] == customer_id
        assert row["invoice_id"] == invoice_id
        assert row["date"] == "2026-03-10"

    def test_unique_credit_note_number_enforced(self, invoice_id, customer_id):
        cn_model.create("CN-DUP", customer_id, invoice_id, "2026-01-01", "First")
        with pytest.raises(Exception):
            cn_model.create("CN-DUP", customer_id, invoice_id, "2026-01-02", "Duplicate")
