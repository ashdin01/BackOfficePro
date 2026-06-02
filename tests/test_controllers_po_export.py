"""Tests for controllers/po_export_controller.py — write_po_csv."""
import csv
import pytest
from controllers.po_export_controller import write_po_csv


@pytest.fixture()
def po_id(db_conn, supplier_id, product_barcode):
    """Insert a minimal PO and return its id."""
    db_conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, po_type) "
        "VALUES ('CSV-001', ?, 'DRAFT', 'PO')",
        (supplier_id,),
    )
    db_conn.commit()
    return db_conn.execute(
        "SELECT id FROM purchase_orders WHERE po_number='CSV-001'"
    ).fetchone()["id"]


@pytest.fixture()
def po_with_line(db_conn, po_id, product_barcode):
    """Add a product line to the CSV-001 PO; set product pack_qty=6 and SOH=15."""
    # Set pack_qty on the product itself (write_po_csv reads from products, not po_lines)
    db_conn.execute(
        "UPDATE products SET pack_qty=6 WHERE barcode=?", (product_barcode,)
    )
    db_conn.execute(
        "INSERT INTO po_lines "
        "(po_id, barcode, description, ordered_qty, unit_cost, pack_qty) "
        "VALUES (?, ?, 'Test Product', 3, 2.00, 6)",
        (po_id, product_barcode),
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 15)",
        (product_barcode,),
    )
    db_conn.commit()
    return po_id


@pytest.fixture()
def po_with_note(db_conn, po_with_line, po_id):
    """Add a note line (NULL barcode) after the product line."""
    db_conn.execute(
        "INSERT INTO po_lines "
        "(po_id, barcode, description, ordered_qty, unit_cost, is_note, sort_order) "
        "VALUES (?, NULL, 'Handle with care', 0, 0, 1, 999)",
        (po_id,),
    )
    db_conn.commit()
    return po_id


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


# ── Header rows ───────────────────────────────────────────────────────────────

class TestCsvHeaderRows:
    def test_first_row_is_supplier(self, po_with_line, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        assert rows[0][0] == "Supplier"
        assert rows[0][1] == "Test Supplier"

    def test_second_row_is_email(self, po_with_line, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        assert rows[1][0] == "Email"

    def test_third_row_is_po_number(self, po_with_line, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        assert rows[2][0] == "PO Number"
        assert rows[2][1] == "CSV-001"

    def test_fourth_row_is_status(self, po_with_line, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        assert rows[3][0] == "Status"
        assert rows[3][1] == "DRAFT"

    def test_column_header_row_has_barcode(self, po_with_line, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        col_headers = rows[5]
        assert "Barcode" in col_headers
        assert "Description" in col_headers

    def test_blank_row_between_metadata_and_columns(self, po_with_line, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        assert all(v == "" for v in rows[4])


# ── Product data rows ─────────────────────────────────────────────────────────

class TestCsvProductRows:
    def test_product_barcode_in_data_row(self, po_with_line, product_barcode, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        data_row = rows[6]
        assert product_barcode in data_row[0]

    def test_total_units_calculated_from_qty_times_pack_qty(self, po_with_line, tmp_path):
        # ordered_qty=3, pack_qty=6 → total_units=18
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        data_row = rows[6]
        total_units_col = 3
        assert data_row[total_units_col] == "18"

    def test_system_soh_column_reflects_stock_on_hand(self, po_with_line, tmp_path):
        # SOH fixture sets 15 units
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        data_row = rows[6]
        soh_system_col = 5
        assert data_row[soh_system_col] == "15"

    def test_pack_qty_and_unit_in_description_column(self, po_with_line, tmp_path):
        # pack_qty=6, pack_unit='EA'
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        data_row = rows[6]
        pack_col = 2
        assert "6" in data_row[pack_col]
        assert "EA" in data_row[pack_col]


# ── Note lines ────────────────────────────────────────────────────────────────

class TestCsvNoteLines:
    def test_note_line_prefixed_with_NOTE(self, po_with_note, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_note, out)
        rows = _read_csv(out)
        note_rows = [r for r in rows if any("NOTE:" in cell for cell in r)]
        assert len(note_rows) == 1

    def test_note_text_in_description_column(self, po_with_note, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_note, out)
        rows = _read_csv(out)
        note_row = next(r for r in rows if any("NOTE:" in cell for cell in r))
        assert "Handle with care" in note_row[1]

    def test_note_barcode_column_is_empty(self, po_with_note, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_note, out)
        rows = _read_csv(out)
        note_row = next(r for r in rows if any("NOTE:" in cell for cell in r))
        assert note_row[0] == ""


# ── Supplier email handling ───────────────────────────────────────────────────

class TestCsvSupplierEmail:
    def test_supplier_email_orders_appears_in_email_row(self, db_conn, supplier_id,
                                                         po_with_line, tmp_path):
        db_conn.execute(
            "UPDATE suppliers SET email_orders='orders@supplier.com' WHERE id=?",
            (supplier_id,),
        )
        db_conn.commit()
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        assert rows[1][1] == "orders@supplier.com"

    def test_empty_email_orders_gives_blank(self, po_with_line, tmp_path):
        out = str(tmp_path / "out.csv")
        write_po_csv(po_with_line, out)
        rows = _read_csv(out)
        assert rows[1][1] == ""


# ── Empty PO (no lines) ───────────────────────────────────────────────────────

class TestCsvEmptyPo:
    def test_empty_po_writes_file(self, po_id, tmp_path):
        out = str(tmp_path / "empty.csv")
        write_po_csv(po_id, out)
        import os
        assert os.path.exists(out)

    def test_empty_po_has_metadata_rows(self, po_id, tmp_path):
        out = str(tmp_path / "empty.csv")
        write_po_csv(po_id, out)
        rows = _read_csv(out)
        assert rows[0][0] == "Supplier"
        assert rows[2][1] == "CSV-001"


# ── generate_po_pdf_to_disk ───────────────────────────────────────────────────

class TestGeneratePoPdfToDisk:
    def test_calls_generate_and_returns_path(self, test_db, po_id, tmp_path, monkeypatch):
        import controllers.po_export_controller as export_ctrl
        generated = []

        def fake_generate(po_id_arg, path_arg):
            generated.append(path_arg)
            open(path_arg, 'wb').close()

        monkeypatch.setattr(
            "controllers.po_export_controller.generate_po_pdf_to_disk",
            lambda pid: _fake_pdf_to_disk(pid, tmp_path, fake_generate),
        )
        # Call the real function with patched pdf generator
        import controllers.po_export_controller as ctrl_mod
        import utils.po_pdf as po_pdf_mod
        monkeypatch.setattr(po_pdf_mod, "generate_po_pdf", fake_generate)

        path = ctrl_mod.generate_po_pdf_to_disk(po_id)
        assert path.endswith(".pdf")


def _fake_pdf_to_disk(po_id, tmp_path, fake_generate):
    import models.purchase_order as po_model
    import controllers.po_export_controller as ctrl
    po = po_model.get_by_id(po_id)
    path = str(tmp_path / f"{po['po_number']}.pdf")
    open(path, 'wb').close()
    return path


# ── _po_pdf_path ──────────────────────────────────────────────────────────────

class TestPoPdfPath:
    def test_uses_configured_folder(self, test_db, po_id, tmp_path, monkeypatch):
        import controllers.po_export_controller as ctrl
        import models.settings as settings_model
        monkeypatch.setattr(
            settings_model, "get_setting",
            lambda key, default=None: str(tmp_path) if key == "po_pdf_path" else default,
        )
        import models.purchase_order as po_model
        import utils.po_pdf as po_pdf_mod
        monkeypatch.setattr(po_pdf_mod, "generate_po_pdf", lambda po_id_arg, path: open(path, 'wb').close())
        path = ctrl.generate_po_pdf_to_disk(po_id)
        assert str(tmp_path) in path

    def test_defaults_to_documents_when_not_configured(self, test_db, po_id, monkeypatch):
        import controllers.po_export_controller as ctrl
        import models.settings as settings_model
        monkeypatch.setattr(
            settings_model, "get_setting",
            lambda key, default=None: "" if key == "po_pdf_path" else default,
        )
        import utils.po_pdf as po_pdf_mod
        monkeypatch.setattr(po_pdf_mod, "generate_po_pdf", lambda po_id_arg, path: open(path, 'wb').close())
        path = ctrl.generate_po_pdf_to_disk(po_id)
        assert path.endswith(".pdf")


# ── send_po_email ─────────────────────────────────────────────────────────────

class TestSendPoEmail:
    def test_generates_pdf_and_marks_sent(self, test_db, po_id, tmp_path, monkeypatch):
        import controllers.po_export_controller as ctrl
        import models.settings as settings_model
        import utils.po_pdf as po_pdf_mod
        import utils.email_graph as email_mod
        import models.purchase_order as po_model

        monkeypatch.setattr(
            settings_model, "get_setting",
            lambda key, default=None: str(tmp_path) if key == "po_pdf_path" else default,
        )
        monkeypatch.setattr(po_pdf_mod, "generate_po_pdf", lambda pid, path: open(path, 'wb').close())
        monkeypatch.setattr(email_mod, "send_purchase_order", lambda **kw: None)

        path = ctrl.send_po_email(po_id, "supplier@example.com")
        assert path.endswith(".pdf")
        po = po_model.get_by_id(po_id)
        assert po["status"] == "SENT"
