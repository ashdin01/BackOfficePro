"""
Smoke tests for generate_po_pdf.

Each test creates the minimum DB state needed (supplier → product → PO → line),
calls generate_po_pdf, and asserts a non-empty PDF was written.  We exercise every
PO type so that type-specific rendering paths (unit_mode, is_return, note lines)
are all covered.
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

    # Note line — empty barcode violates FK; use a direct connection without FK enforcement
    raw = sqlite3.connect(test_db)
    raw.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, is_note, sort_order)"
        " VALUES (?, '', 'Handle with care', 0, 0, 1, 999)",
        (po_id,),
    )
    raw.commit()
    raw.close()

    out = str(tmp_path / "smoke_note.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0
