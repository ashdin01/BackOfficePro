"""
Smoke tests for generate_po_pdf.

Each test creates the minimum DB state needed (supplier → product → PO → line),
calls generate_po_pdf, and asserts a non-empty PDF was written.  We exercise every
PO type so that type-specific rendering paths (unit_mode, is_return, note lines,
charges) are all covered.
"""
import os
import sqlite3
import pytest
from utils.po_pdf import generate_po_pdf


# ── Shared helpers ────────────────────────────────────────────────────────────

@pytest.fixture()
def _po(db_conn, supplier_id, product_barcode):
    """Return a factory: _po(po_type) → po_id with one product line."""
    def _make(po_type):
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
            " VALUES (?, ?, 'DRAFT', ?)",
            (f"SMOKE-{po_type}-001", supplier_id, po_type),
        )
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number=?",
            (f"SMOKE-{po_type}-001",),
        ).fetchone()["id"]
        db_conn.execute(
            "INSERT INTO po_lines"
            " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
            " VALUES (?, ?, 'Test Product', 5, 2.00, 6)",
            (po_id, product_barcode),
        )
        db_conn.commit()
        return po_id
    return _make


# ── PO type smoke tests ───────────────────────────────────────────────────────

@pytest.mark.parametrize("po_type", ["PO", "RO", "IO"])
def test_pdf_generated_for_po_type(tmp_path, _po, po_type):
    """generate_po_pdf writes a non-empty file for every PO type."""
    po_id = _po(po_type)
    out = str(tmp_path / f"smoke_{po_type}.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0


# ── Note-line regression test ─────────────────────────────────────────────────

def test_pdf_generated_with_note_line(tmp_path, test_db, db_conn, supplier_id, product_barcode):
    """A PO containing a note line renders without error.

    Note lines are inserted via a raw sqlite3 connection (bypassing FK enforcement)
    because they carry an empty barcode, matching the application's own add_note path.
    """
    db_conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
        " VALUES ('SMOKE-NOTE-001', ?, 'DRAFT', 'PO')",
        (supplier_id,),
    )
    db_conn.commit()
    po_id = db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='SMOKE-NOTE-001'"
    ).fetchone()["id"]

    # Product line (FK-safe via db_conn)
    db_conn.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
        " VALUES (?, ?, 'Test Product', 3, 1.50, 1)",
        (po_id, product_barcode),
    )
    db_conn.commit()

    # Note line — barcode is NULL (no FK check for NULL, no workaround needed)
    db_conn.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, is_note, sort_order)"
        " VALUES (?, NULL, 'Handle with care', 0, 0, 1, 999)",
        (po_id,),
    )
    db_conn.commit()

    out = str(tmp_path / "smoke_note.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0


# ── Credit / Return PO type ───────────────────────────────────────────────────

def test_pdf_generated_for_credit_po(tmp_path, _po):
    """CREDIT PO type (credit/return) renders without error."""
    po_id = _po("CREDIT")
    out = str(tmp_path / "smoke_credit.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── PO with po_charges rows ───────────────────────────────────────────────────

def test_pdf_generated_with_charges(tmp_path, test_db, db_conn, supplier_id, product_barcode):
    """A PO with freight / surcharge rows in po_charges renders correctly."""
    db_conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
        " VALUES ('SMOKE-CHARGE-001', ?, 'RECEIVED', 'PO')",
        (supplier_id,),
    )
    db_conn.commit()
    po_id = db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='SMOKE-CHARGE-001'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty, received_qty)"
        " VALUES (?, ?, 'Test Product', 5, 2.00, 6, 5)",
        (po_id, product_barcode),
    )
    db_conn.execute(
        "INSERT INTO po_charges (po_id, description, tax_rate, amount_inc_tax)"
        " VALUES (?, 'Freight', 10.0, 33.00)",
        (po_id,),
    )
    db_conn.execute(
        "INSERT INTO po_charges (po_id, description, tax_rate, amount_inc_tax)"
        " VALUES (?, 'Handling fee', 0.0, 5.00)",
        (po_id,),
    )
    db_conn.commit()

    out = str(tmp_path / "smoke_charges.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── PO with supplier invoice number ──────────────────────────────────────────

def test_pdf_with_supplier_invoice_number(tmp_path, test_db, db_conn, supplier_id, product_barcode):
    """A received PO with a supplier invoice number renders the invoice field."""
    db_conn.execute(
        "INSERT INTO purchase_orders"
        " (po_number, supplier_id, status, po_type, supplier_invoice_number)"
        " VALUES ('SMOKE-INV-001', ?, 'RECEIVED', 'PO', 'SUPINV-9999')",
        (supplier_id,),
    )
    db_conn.commit()
    po_id = db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='SMOKE-INV-001'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
        " VALUES (?, ?, 'Test Product', 2, 1.50, 1)",
        (po_id, product_barcode),
    )
    db_conn.commit()

    out = str(tmp_path / "smoke_inv.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── PO with no lines ─────────────────────────────────────────────────────────

def test_pdf_with_no_lines(tmp_path, test_db, db_conn, supplier_id):
    """A PO with no lines must still produce a valid PDF."""
    db_conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
        " VALUES ('SMOKE-EMPTY-001', ?, 'DRAFT', 'PO')",
        (supplier_id,),
    )
    db_conn.commit()
    po_id = db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='SMOKE-EMPTY-001'"
    ).fetchone()["id"]

    out = str(tmp_path / "smoke_empty.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── Return path ───────────────────────────────────────────────────────────────

def test_pdf_returns_output_path_unchanged(tmp_path, _po):
    """generate_po_pdf must return exactly the path that was passed in."""
    po_id = _po("PO")
    explicit_path = str(tmp_path / "subfolder" / "my_po.pdf")
    os.makedirs(os.path.dirname(explicit_path), exist_ok=True)
    result = generate_po_pdf(po_id, explicit_path)
    assert result == explicit_path
