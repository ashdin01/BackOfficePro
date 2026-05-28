"""Tests for PO note lines, sort order, po_charges, and receive_po_atomic."""
import pytest
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.po_charges as charges_model
import controllers.purchase_order_controller as po_ctrl


# ── Note line insertion ───────────────────────────────────────────────────────

class TestPoNoteLines:
    def test_add_note_returns_id(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        note_id = lines_model.add_note(po_id, "Handle with care")
        assert isinstance(note_id, int) and note_id > 0

    def test_note_line_has_is_note_flag(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add_note(po_id, "Fragile")
        lines = lines_model.get_by_po(po_id)
        assert lines[0]["is_note"] == 1

    def test_note_line_description_stored(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add_note(po_id, "Deliver before noon")
        lines = lines_model.get_by_po(po_id)
        assert lines[0]["description"] == "Deliver before noon"

    def test_note_line_has_zero_qty_and_cost(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add_note(po_id, "Note text")
        lines = lines_model.get_by_po(po_id)
        assert lines[0]["ordered_qty"] == 0
        assert float(lines[0]["unit_cost"]) == pytest.approx(0.0)

    def test_note_line_has_null_barcode(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add_note(po_id, "Note text")
        lines = lines_model.get_by_po(po_id)
        assert lines[0]["barcode"] is None

    def test_multiple_notes_added(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add_note(po_id, "Note 1")
        lines_model.add_note(po_id, "Note 2")
        lines = lines_model.get_by_po(po_id)
        assert len(lines) == 2


# ── Sort order / renumber ─────────────────────────────────────────────────────

class TestSortOrder:
    def test_renumber_sort_order_applies_multiples_of_ten(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Product A", 1, 5.00)
        lines_model.add_note(po_id, "Note after A")
        lines = lines_model.get_by_po(po_id)
        ordered_ids = [l["id"] for l in lines]
        lines_model.renumber_sort_order(po_id, ordered_ids)
        updated = lines_model.get_by_po(po_id)
        sort_orders = [l["sort_order"] for l in updated]
        assert sort_orders == [10, 20]

    def test_get_by_po_respects_sort_order(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Line A", 1, 5.00)
        lines_model.add_note(po_id, "Note in middle")
        lines_model.add(po_id, product_barcode, "Line B", 2, 3.00)
        # Renumber: note in position 2, Line B in position 3
        all_lines = lines_model.get_by_po(po_id)
        # Swap so note is between the two product lines
        ids_reordered = [all_lines[0]["id"], all_lines[2]["id"], all_lines[1]["id"]]
        lines_model.renumber_sort_order(po_id, ids_reordered)
        result = lines_model.get_by_po(po_id)
        assert result[0]["description"] == "Line A"
        assert result[1]["description"] == "Line B"
        assert result[2]["description"] == "Note in middle"

    def test_renumber_with_single_line(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Only line", 1, 5.00)
        lines = lines_model.get_by_po(po_id)
        lines_model.renumber_sort_order(po_id, [lines[0]["id"]])
        updated = lines_model.get_by_po(po_id)
        assert updated[0]["sort_order"] == 10


# ── po_charges model ──────────────────────────────────────────────────────────

class TestPoCharges:
    def test_save_and_get_charges(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        charges_model.save_charges(po_id, [
            {"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 22.00},
            {"description": "Fuel Levy", "tax_rate": 0.0, "amount_inc_tax": 5.00},
        ])
        result = charges_model.get_by_po(po_id)
        assert len(result) == 2
        assert result[0]["description"] == "Freight"
        assert float(result[0]["amount_inc_tax"]) == pytest.approx(22.00)

    def test_save_charges_replaces_existing(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        charges_model.save_charges(po_id, [
            {"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 22.00},
        ])
        charges_model.save_charges(po_id, [
            {"description": "New Charge", "tax_rate": 0.0, "amount_inc_tax": 10.00},
        ])
        result = charges_model.get_by_po(po_id)
        assert len(result) == 1
        assert result[0]["description"] == "New Charge"

    def test_save_empty_charges_clears_existing(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        charges_model.save_charges(po_id, [
            {"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 22.00},
        ])
        charges_model.save_charges(po_id, [])
        assert charges_model.get_by_po(po_id) == []

    def test_get_by_po_empty_if_none(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        assert charges_model.get_by_po(po_id) == []

    def test_charges_isolated_by_po(self, test_db, supplier_id):
        po1 = po_model.create(supplier_id, "2026-06-01", "", "admin")
        po2 = po_model.create(supplier_id, "2026-06-02", "", "admin")
        charges_model.save_charges(po1, [
            {"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 22.00},
        ])
        assert charges_model.get_by_po(po2) == []

    def test_charge_tax_rate_stored(self, test_db, supplier_id):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        charges_model.save_charges(po_id, [
            {"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 22.00},
        ])
        result = charges_model.get_by_po(po_id)
        assert float(result[0]["tax_rate"]) == pytest.approx(10.0)


# ── receive_po_atomic with supplier_invoice_number and charges ────────────────

class TestReceivePoAtomic:
    def _make_sent_po(self, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 5, 2.00)
        po_model.update_status(po_id, "SENT")
        return po_id

    def test_supplier_invoice_number_saved(self, test_db, supplier_id, product_barcode):
        po_id = self._make_sent_po(supplier_id, product_barcode)
        lines = lines_model.get_by_po(po_id)
        po_ctrl.receive_po_atomic(
            po_id,
            po_model.get_by_id(po_id)["po_number"],
            [{
                "line_id": lines[0]["id"],
                "barcode": product_barcode,
                "new_received_qty": 5,
                "qty_units": 5,
                "unit_cost": 2.00,
                "actual_cost": 10.00,
                "is_promo": False,
            }],
            final_status="RECEIVED",
            supplier_invoice_number="SINV-12345",
        )
        po = po_model.get_by_id(po_id)
        assert po["supplier_invoice_number"] == "SINV-12345"

    def test_charges_saved_during_receive(self, test_db, supplier_id, product_barcode):
        po_id = self._make_sent_po(supplier_id, product_barcode)
        lines = lines_model.get_by_po(po_id)
        po_ctrl.receive_po_atomic(
            po_id,
            po_model.get_by_id(po_id)["po_number"],
            [{
                "line_id": lines[0]["id"],
                "barcode": product_barcode,
                "new_received_qty": 5,
                "qty_units": 5,
                "unit_cost": 2.00,
                "actual_cost": 10.00,
                "is_promo": False,
            }],
            final_status="RECEIVED",
            supplier_invoice_number="SINV-99999",
            charges=[
                {"description": "Freight", "tax_rate": 10.0, "amount_inc_tax": 22.00},
            ],
        )
        result = charges_model.get_by_po(po_id)
        assert len(result) == 1
        assert result[0]["description"] == "Freight"

    def test_receive_without_charges_leaves_charges_empty(self, test_db, supplier_id, product_barcode):
        po_id = self._make_sent_po(supplier_id, product_barcode)
        lines = lines_model.get_by_po(po_id)
        po_ctrl.receive_po_atomic(
            po_id,
            po_model.get_by_id(po_id)["po_number"],
            [{
                "line_id": lines[0]["id"],
                "barcode": product_barcode,
                "new_received_qty": 5,
                "qty_units": 5,
                "unit_cost": 2.00,
                "actual_cost": 10.00,
                "is_promo": False,
            }],
            final_status="RECEIVED",
            supplier_invoice_number="SINV-00001",
        )
        assert charges_model.get_by_po(po_id) == []

    def test_receive_sets_po_status(self, test_db, supplier_id, product_barcode):
        po_id = self._make_sent_po(supplier_id, product_barcode)
        lines = lines_model.get_by_po(po_id)
        po_ctrl.receive_po_atomic(
            po_id,
            po_model.get_by_id(po_id)["po_number"],
            [{
                "line_id": lines[0]["id"],
                "barcode": product_barcode,
                "new_received_qty": 5,
                "qty_units": 5,
                "unit_cost": 2.00,
                "actual_cost": 10.00,
                "is_promo": False,
            }],
            final_status="RECEIVED",
            supplier_invoice_number="SINV-00002",
        )
        assert po_model.get_by_id(po_id)["status"] == "RECEIVED"
