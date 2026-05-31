"""Tests for controllers/purchase_order_controller.py — DB-backed tests."""
import pytest
from controllers.purchase_order_controller import (
    create_po,
    get_po_by_id,
    get_po_with_supplier,
    get_all_pos,
    get_po_lines,
    add_po_line,
    update_po_line,
    delete_po_line,
    add_po_note_line,
    update_po_status,
    cancel_po,
    delete_draft_po,
    get_unreceived_lines,
    get_received_line_count,
    receive_po_atomic,
    close_po_force,
    get_po_charges,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_po(supplier_id, **kwargs):
    return create_po(supplier_id, **kwargs)


def _add_line(po_id, barcode, desc='Widget', qty=5, cost=2.50):
    add_po_line(po_id, barcode, desc, qty, unit_cost=cost)


def _get_lines(po_id):
    return get_po_lines(po_id)


# ── Create PO ─────────────────────────────────────────────────────────────────

class TestCreatePO:
    def test_returns_positive_integer_id(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        assert isinstance(po_id, int) and po_id > 0

    def test_creates_with_draft_status(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        po = get_po_by_id(po_id)
        assert po['status'] == 'DRAFT'

    def test_po_number_uses_prefix(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        po = get_po_by_id(po_id)
        assert po['po_number'].startswith('PO-')

    def test_sequential_po_numbers(self, test_db, supplier_id):
        id1 = _make_po(supplier_id)
        id2 = _make_po(supplier_id)
        po1 = get_po_by_id(id1)
        po2 = get_po_by_id(id2)
        seq1 = int(po1['po_number'].split('-')[1])
        seq2 = int(po2['po_number'].split('-')[1])
        assert seq2 == seq1 + 1

    def test_optional_fields_stored(self, test_db, supplier_id):
        po_id = _make_po(supplier_id, delivery_date='2026-06-01',
                         notes='Test notes', created_by='alice')
        po = get_po_by_id(po_id)
        assert po['delivery_date'] == '2026-06-01'
        assert po['notes'] == 'Test notes'
        assert po['created_by'] == 'alice'

    def test_po_type_stored(self, test_db, supplier_id):
        po_id = _make_po(supplier_id, po_type='CREDIT')
        po = get_po_by_id(po_id)
        assert po['po_type'] == 'CREDIT'

    def test_get_po_with_supplier_returns_supplier_name(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        po = get_po_with_supplier(po_id)
        assert po is not None
        assert po['supplier_name'] == 'Test Supplier'

    def test_get_po_with_supplier_returns_none_for_missing(self, test_db, supplier_id):
        result = get_po_with_supplier(999999)
        assert result is None


# ── Get / List POs ────────────────────────────────────────────────────────────

class TestListPOs:
    def test_get_all_pos_returns_draft_by_default(self, test_db, supplier_id):
        _make_po(supplier_id)
        pos = get_all_pos()
        assert len(pos) >= 1
        for po in pos:
            assert po['status'] in ('DRAFT', 'SENT', 'PARTIAL')

    def test_filter_by_status(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        update_po_status(po_id, 'SENT')
        sent = get_all_pos(status='SENT')
        assert any(p['id'] == po_id for p in sent)

    def test_archived_returns_received_cancelled(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        cancel_po(po_id)
        archived = get_all_pos(archived=True)
        assert any(p['id'] == po_id for p in archived)

    def test_get_po_by_id_returns_none_for_missing(self, test_db, supplier_id):
        assert get_po_by_id(999999) is None

    def test_get_po_by_id_includes_supplier_name(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        po = get_po_by_id(po_id)
        assert po['supplier_name'] == 'Test Supplier'


# ── Add / Update / Delete PO Lines ───────────────────────────────────────────

class TestPOLines:
    def test_add_line_appears_in_get_lines(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=3, cost=1.50)
        lines = _get_lines(po_id)
        assert len(lines) == 1
        assert lines[0]['barcode'] == product_barcode
        assert lines[0]['ordered_qty'] == 3

    def test_add_multiple_lines(self, test_db, supplier_id, product_barcode, gst_free_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=2, cost=1.00)
        _add_line(po_id, gst_free_barcode, desc='GST Free', qty=4, cost=0.80)
        lines = _get_lines(po_id)
        assert len(lines) == 2

    def test_update_po_line(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=2, cost=1.00)
        line = _get_lines(po_id)[0]
        update_po_line(line['id'], ordered_qty=10, unit_cost=3.00, notes='updated')
        updated = _get_lines(po_id)[0]
        assert updated['ordered_qty'] == 10
        assert updated['unit_cost'] == 3.00
        assert updated['notes'] == 'updated'

    def test_delete_po_line(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode)
        line = _get_lines(po_id)[0]
        delete_po_line(line['id'])
        assert _get_lines(po_id) == []

    def test_add_note_line(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        add_po_note_line(po_id, 'Deliver before noon')
        lines = _get_lines(po_id)
        assert len(lines) == 1
        assert lines[0]['is_note'] == 1
        assert lines[0]['description'] == 'Deliver before noon'

    def test_add_line_zero_qty_raises(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        with pytest.raises(ValueError):
            add_po_line(po_id, product_barcode, 'Widget', ordered_qty=0, unit_cost=1.00)

    def test_add_line_negative_qty_raises(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        with pytest.raises(ValueError):
            add_po_line(po_id, product_barcode, 'Widget', ordered_qty=-5, unit_cost=1.00)

    def test_add_line_negative_cost_raises(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        with pytest.raises(ValueError):
            add_po_line(po_id, product_barcode, 'Widget', ordered_qty=5, unit_cost=-1.00)


# ── Status Transitions ────────────────────────────────────────────────────────

class TestStatusTransitions:
    def test_draft_to_sent(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        update_po_status(po_id, 'SENT')
        assert get_po_by_id(po_id)['status'] == 'SENT'

    def test_sent_to_partial(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        update_po_status(po_id, 'SENT')
        update_po_status(po_id, 'PARTIAL')
        assert get_po_by_id(po_id)['status'] == 'PARTIAL'

    def test_cancel_po_sets_cancelled(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        cancel_po(po_id)
        assert get_po_by_id(po_id)['status'] == 'CANCELLED'

    def test_delete_draft_po_sets_cancelled(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        delete_draft_po(po_id)
        assert get_po_by_id(po_id)['status'] == 'CANCELLED'

    def test_cancelled_po_not_in_active_list(self, test_db, supplier_id):
        po_id = _make_po(supplier_id)
        cancel_po(po_id)
        active = get_all_pos()
        assert not any(p['id'] == po_id for p in active)


# ── Receive PO (atomic) ───────────────────────────────────────────────────────

class TestReceivePO:
    def _make_receipt(self, line, qty_units, actual_cost=2.00, unit_cost=2.00):
        return {
            'line_id':         line['id'],
            'barcode':         line['barcode'],
            'new_received_qty': qty_units,
            'actual_cost':     actual_cost,
            'unit_cost':       unit_cost,
            'is_promo':        False,
            'qty_units':       qty_units,
        }

    def test_full_receipt_sets_status_received(self, test_db, supplier_id, product_barcode, db_conn):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=5, cost=2.00)
        line = _get_lines(po_id)[0]
        po = get_po_by_id(po_id)
        receive_po_atomic(
            po_id, po['po_number'],
            [self._make_receipt(line, 5)],
            final_status='RECEIVED',
        )
        assert get_po_by_id(po_id)['status'] == 'RECEIVED'

    def test_receipt_increases_soh(self, test_db, supplier_id, product_barcode, db_conn):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=10, cost=2.00)
        line = _get_lines(po_id)[0]
        po = get_po_by_id(po_id)
        receive_po_atomic(
            po_id, po['po_number'],
            [self._make_receipt(line, 10)],
            final_status='RECEIVED',
        )
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        assert row is not None
        assert row['quantity'] == 10

    def test_partial_receipt_sets_partial_status(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=10, cost=2.00)
        line = _get_lines(po_id)[0]
        po = get_po_by_id(po_id)
        receive_po_atomic(
            po_id, po['po_number'],
            [self._make_receipt(line, 3)],
            final_status='PARTIAL',
        )
        assert get_po_by_id(po_id)['status'] == 'PARTIAL'

    def test_get_unreceived_lines_after_partial(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=10, cost=2.00)
        line = _get_lines(po_id)[0]
        po = get_po_by_id(po_id)
        receive_po_atomic(
            po_id, po['po_number'],
            [self._make_receipt(line, 3)],
            final_status='PARTIAL',
        )
        unreceived = get_unreceived_lines(po_id)
        assert len(unreceived) == 1
        assert unreceived[0]['ordered_qty'] == 10

    def test_get_received_line_count(self, test_db, supplier_id, product_barcode, gst_free_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=5, cost=2.00)
        _add_line(po_id, gst_free_barcode, desc='GST Free', qty=3, cost=1.00)
        lines = _get_lines(po_id)
        po = get_po_by_id(po_id)
        # Receive only the first line
        receive_po_atomic(
            po_id, po['po_number'],
            [self._make_receipt(lines[0], 5)],
            final_status='PARTIAL',
        )
        assert get_received_line_count(po_id) == 1

    def test_receipt_stores_supplier_invoice_number(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=5, cost=2.00)
        line = _get_lines(po_id)[0]
        po = get_po_by_id(po_id)
        receive_po_atomic(
            po_id, po['po_number'],
            [self._make_receipt(line, 5)],
            final_status='RECEIVED',
            supplier_invoice_number='INV-12345',
        )
        received_po = get_po_by_id(po_id)
        assert received_po['supplier_invoice_number'] == 'INV-12345'

    def test_receipt_with_charge_stored(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=5, cost=2.00)
        line = _get_lines(po_id)[0]
        po = get_po_by_id(po_id)
        charges = [{'description': 'Freight', 'tax_rate': 10.0, 'amount_inc_tax': 15.00}]
        receive_po_atomic(
            po_id, po['po_number'],
            [self._make_receipt(line, 5)],
            final_status='RECEIVED',
            charges=charges,
        )
        stored = get_po_charges(po_id)
        assert len(stored) == 1
        assert stored[0]['description'] == 'Freight'

    def test_invalid_charge_raises_before_db_write(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=5, cost=2.00)
        line = _get_lines(po_id)[0]
        po = get_po_by_id(po_id)
        bad_charges = [{'description': '', 'tax_rate': 10.0, 'amount_inc_tax': 5.00}]
        with pytest.raises(ValueError):
            receive_po_atomic(
                po_id, po['po_number'],
                [self._make_receipt(line, 5)],
                final_status='RECEIVED',
                charges=bad_charges,
            )
        # PO status must be unchanged after a rejected receipt
        assert get_po_by_id(po_id)['status'] == 'DRAFT'


# ── Close PO Force ─────────────────────────────────────────────────────────────

class TestClosePOForce:
    def test_close_force_marks_lines_not_supplied(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=5, cost=2.00)
        line = _get_lines(po_id)[0]
        close_po_force(po_id, [line['id']], reason='Out of stock')
        updated_lines = _get_lines(po_id)
        assert 'NOT SUPPLIED' in (updated_lines[0]['notes'] or '')

    def test_close_force_sets_received_status(self, test_db, supplier_id, product_barcode):
        po_id = _make_po(supplier_id)
        _add_line(po_id, product_barcode, qty=5, cost=2.00)
        line = _get_lines(po_id)[0]
        close_po_force(po_id, [line['id']], reason='No stock')
        assert get_po_by_id(po_id)['status'] == 'RECEIVED'
