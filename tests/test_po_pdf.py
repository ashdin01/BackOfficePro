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
import models.product_suppliers as ps_model


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


# ── Missing PO ─────────────────────────────────────────────────────────────────

def test_missing_po_raises_value_error(tmp_path, test_db):
    with pytest.raises(ValueError, match="not found"):
        generate_po_pdf(99999, str(tmp_path / "nope.pdf"))


# ── Store details header line ───────────────────────────────────────────────────

def test_pdf_renders_store_address_phone_and_abn(tmp_path, test_db, db_conn, _po):
    db_conn.executemany(
        "UPDATE settings SET value=? WHERE key=?",
        [
            ("1 Test Street, Testville", "store_address"),
            ("03 5555 5555", "store_phone"),
            ("12 345 678 901", "store_abn"),
        ],
    )
    db_conn.commit()
    po_id = _po("PO")
    out = str(tmp_path / "smoke_store_details.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── Supplier payment terms ───────────────────────────────────────────────────────

def test_pdf_renders_supplier_payment_terms(tmp_path, test_db, db_conn, supplier_id, _po):
    db_conn.execute(
        "UPDATE suppliers SET payment_terms='Net 30' WHERE id=?", (supplier_id,)
    )
    db_conn.commit()
    po_id = _po("PO")
    out = str(tmp_path / "smoke_terms.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── PO notes ──────────────────────────────────────────────────────────────────

def test_pdf_renders_po_notes(tmp_path, test_db, db_conn, supplier_id, product_barcode):
    db_conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type, notes)"
        " VALUES ('SMOKE-NOTES-001', ?, 'DRAFT', 'PO', 'Deliver to back door')",
        (supplier_id,),
    )
    db_conn.commit()
    po_id = db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='SMOKE-NOTES-001'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
        " VALUES (?, ?, 'Test Product', 2, 1.50, 1)",
        (po_id, product_barcode),
    )
    db_conn.commit()

    out = str(tmp_path / "smoke_notes.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── Non-numeric unit cost ────────────────────────────────────────────────────────

def test_pdf_handles_non_numeric_unit_cost(tmp_path, test_db, db_conn, supplier_id, product_barcode):
    """A line with a corrupt/non-numeric unit_cost renders with placeholder text
    instead of crashing (the except TypeError/ValueError branch)."""
    db_conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
        " VALUES ('SMOKE-BADCOST-001', ?, 'DRAFT', 'PO')",
        (supplier_id,),
    )
    db_conn.commit()
    po_id = db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='SMOKE-BADCOST-001'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
        " VALUES (?, ?, 'Test Product', 2, 'N/A', 1)",
        (po_id, product_barcode),
    )
    db_conn.commit()

    out = str(tmp_path / "smoke_badcost.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out
    assert os.path.getsize(out) > 0


# ── Carton-mode line with pack_qty > 1 ───────────────────────────────────────────

def test_pdf_carton_mode_with_pack_qty_shows_carton_and_unit_count(
    tmp_path, test_db, db_conn, dept_id, supplier_id
):
    """PO (carton-mode) line for a product with pack_qty > 1 shows both the
    carton count and the converted unit count (qty_str's pack_qty>1 branch).
    The product_barcode fixture pins pack_qty=1, so this needs its own product."""
    bc = "9300000077001"
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, 'Carton Product', ?, ?, 5.00, 3.00, 10.0, 6, 'CTN', 1, 'EA')
    """, (bc, dept_id, supplier_id))
    db_conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
        " VALUES ('SMOKE-PACKQTY-001', ?, 'DRAFT', 'PO')",
        (supplier_id,),
    )
    db_conn.commit()
    po_id = db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='SMOKE-PACKQTY-001'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO po_lines"
        " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
        " VALUES (?, ?, 'Carton Product', 3, 12.00, 6)",
        (po_id, bc),
    )
    db_conn.commit()

    out = str(tmp_path / "smoke_packqty.pdf")
    result = generate_po_pdf(po_id, out)
    assert result == out


# ── Per-supplier SKU / pack size ─────────────────────────────────────────────────
#
# The "Bonsoy Milk" scenario: a product with a default supplier (e.g. Spiral
# Foods) that's also linked to an alternate supplier (e.g. Fords Dairy) with
# a different SKU and pack size. A PO raised against the alternate supplier
# must print *that* supplier's SKU/pack — not the product's default.

@pytest.fixture()
def second_supplier_id(db_conn):
    db_conn.execute("INSERT INTO suppliers (code, name) VALUES ('FORDS', 'Fords Dairy')")
    db_conn.commit()
    return db_conn.execute("SELECT id FROM suppliers WHERE code='FORDS'").fetchone()["id"]


def _spy_paragraph_text(monkeypatch):
    """Patch utils.po_pdf.Paragraph to record every string rendered into the
    PDF while still building real Paragraph flowables, so generate_po_pdf
    completes normally and we can inspect exactly what text was used."""
    import utils.po_pdf as po_pdf_mod
    from reportlab.platypus import Paragraph as RealParagraph

    captured = []

    def spy(text, *args, **kwargs):
        captured.append(text)
        return RealParagraph(text, *args, **kwargs)

    monkeypatch.setattr(po_pdf_mod, "Paragraph", spy)
    return captured


class TestPerSupplierSkuAndPack:
    def test_pdf_shows_alternate_suppliers_sku_not_default(
        self, tmp_path, db_conn, supplier_id, second_supplier_id, product_barcode, monkeypatch
    ):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "SPIRAL-123", "pack_qty": 12, "pack_unit": "CTN"},
            {"supplier_id": second_supplier_id, "is_default": False,
             "supplier_sku": "FORDS-456", "pack_qty": 6, "pack_unit": "CTN"},
        ])
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
            " VALUES ('SMOKE-ALTSUP-001', ?, 'DRAFT', 'PO')",
            (second_supplier_id,),
        )
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='SMOKE-ALTSUP-001'"
        ).fetchone()["id"]
        db_conn.execute(
            "INSERT INTO po_lines"
            " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
            " VALUES (?, ?, 'Bonsoy Milk', 3, 4.00, 6)",
            (po_id, product_barcode),
        )
        db_conn.commit()

        captured = _spy_paragraph_text(monkeypatch)
        generate_po_pdf(po_id, str(tmp_path / "altsup.pdf"))

        assert any("FORDS-456" in t for t in captured), captured
        assert not any("SPIRAL-123" in t for t in captured), captured

    def test_pdf_shows_default_suppliers_sku_when_po_is_for_default(
        self, tmp_path, db_conn, supplier_id, second_supplier_id, product_barcode, monkeypatch
    ):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "SPIRAL-123", "pack_qty": 12, "pack_unit": "CTN"},
            {"supplier_id": second_supplier_id, "is_default": False,
             "supplier_sku": "FORDS-456", "pack_qty": 6, "pack_unit": "CTN"},
        ])
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
            " VALUES ('SMOKE-DEFSUP-001', ?, 'DRAFT', 'PO')",
            (supplier_id,),
        )
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='SMOKE-DEFSUP-001'"
        ).fetchone()["id"]
        db_conn.execute(
            "INSERT INTO po_lines"
            " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
            " VALUES (?, ?, 'Bonsoy Milk', 3, 4.00, 12)",
            (po_id, product_barcode),
        )
        db_conn.commit()

        captured = _spy_paragraph_text(monkeypatch)
        generate_po_pdf(po_id, str(tmp_path / "defsup.pdf"))

        assert any("SPIRAL-123" in t for t in captured), captured
        assert not any("FORDS-456" in t for t in captured), captured

    def test_falls_back_to_product_default_when_no_explicit_link(
        self, tmp_path, db_conn, supplier_id, product_barcode, monkeypatch
    ):
        """A PO line for a product that was never linked via product_suppliers
        (pre-v14 data, or added before a supplier link existed) must still
        render using the product's own default fields, not crash or blank out."""
        db_conn.execute(
            "UPDATE products SET supplier_sku='LEGACY-SKU' WHERE barcode=?",
            (product_barcode,),
        )
        db_conn.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
            " VALUES ('SMOKE-NOLINK-001', ?, 'DRAFT', 'PO')",
            (supplier_id,),
        )
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='SMOKE-NOLINK-001'"
        ).fetchone()["id"]
        db_conn.execute(
            "INSERT INTO po_lines"
            " (po_id, barcode, description, ordered_qty, unit_cost, pack_qty)"
            " VALUES (?, ?, 'Unlinked Product', 3, 4.00, 1)",
            (po_id, product_barcode),
        )
        db_conn.commit()

        captured = _spy_paragraph_text(monkeypatch)
        generate_po_pdf(po_id, str(tmp_path / "nolink.pdf"))

        assert any("LEGACY-SKU" in t for t in captured), captured
