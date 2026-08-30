"""Tests for models/held_sale.py — the POS suspend/resume-sale feature."""
import pytest
import models.held_sale as held_sale_model


def _items(barcode="9300000000001"):
    return [{
        'barcode': barcode, 'description': 'Test Product', 'qty': 2,
        'unit_price': 5.00, 'tax_rate': 10.0, 'price_reason': '',
    }]


class TestCreate:
    def test_returns_unique_incrementing_reference(self, test_db):
        first = held_sale_model.create('POS-001', 'ashley', _items(),
                                       subtotal=9.09, gst_amount=0.91, total=10.00)
        second = held_sale_model.create('POS-001', 'ashley', _items(),
                                        subtotal=9.09, gst_amount=0.91, total=10.00)
        assert first['reference'] != second['reference']
        assert first['reference'].startswith('HLD-')
        assert second['reference'].startswith('HLD-')

    def test_stores_lines(self, test_db):
        held = held_sale_model.create('POS-001', 'ashley', _items(),
                                      subtotal=9.09, gst_amount=0.91, total=10.00)
        full = held_sale_model.get_by_reference(held['reference'])
        assert len(full['lines']) == 1
        assert full['lines'][0]['barcode'] == "9300000000001"
        assert full['lines'][0]['qty'] == 2

    def test_status_defaults_to_open(self, test_db):
        held = held_sale_model.create('POS-001', 'ashley', _items(),
                                      subtotal=9.09, gst_amount=0.91, total=10.00)
        full = held_sale_model.get_by_reference(held['reference'])
        assert full['status'] == 'OPEN'


class TestGetOpen:
    def test_excludes_resumed_and_voided(self, test_db):
        open_hold    = held_sale_model.create('POS-001', 'a', _items(),
                                              subtotal=9.09, gst_amount=0.91, total=10.00)
        resumed_hold = held_sale_model.create('POS-002', 'b', _items(),
                                              subtotal=9.09, gst_amount=0.91, total=10.00)
        voided_hold  = held_sale_model.create('POS-003', 'c', _items(),
                                              subtotal=9.09, gst_amount=0.91, total=10.00)
        held_sale_model.resume_atomic(resumed_hold['reference'], 'POS-002')
        held_sale_model.void(voided_hold['reference'])

        refs = [h['reference'] for h in held_sale_model.get_open()]
        assert refs == [open_hold['reference']]


class TestResumeAtomic:
    def test_transitions_open_to_resumed_and_returns_lines(self, test_db):
        held = held_sale_model.create('POS-001', 'ashley', _items(),
                                      subtotal=9.09, gst_amount=0.91, total=10.00)
        resumed = held_sale_model.resume_atomic(held['reference'], 'POS-002')
        assert resumed['status'] == 'RESUMED'
        assert len(resumed['lines']) == 1

    def test_second_resume_of_same_reference_raises(self, test_db):
        held = held_sale_model.create('POS-001', 'ashley', _items(),
                                      subtotal=9.09, gst_amount=0.91, total=10.00)
        held_sale_model.resume_atomic(held['reference'], 'POS-002')
        with pytest.raises(ValueError):
            held_sale_model.resume_atomic(held['reference'], 'POS-003')

    def test_unknown_reference_raises_lookup_error(self, test_db):
        with pytest.raises(LookupError):
            held_sale_model.resume_atomic('HLD-99999', 'POS-002')

    def test_resuming_voided_hold_raises(self, test_db):
        held = held_sale_model.create('POS-001', 'ashley', _items(),
                                      subtotal=9.09, gst_amount=0.91, total=10.00)
        held_sale_model.void(held['reference'])
        with pytest.raises(ValueError):
            held_sale_model.resume_atomic(held['reference'], 'POS-002')


class TestVoid:
    def test_transitions_open_to_voided(self, test_db):
        held = held_sale_model.create('POS-001', 'ashley', _items(),
                                      subtotal=9.09, gst_amount=0.91, total=10.00)
        held_sale_model.void(held['reference'])
        full = held_sale_model.get_by_reference(held['reference'])
        assert full['status'] == 'VOIDED'

    def test_unknown_reference_raises_lookup_error(self, test_db):
        with pytest.raises(LookupError):
            held_sale_model.void('HLD-99999')

    def test_voiding_already_voided_hold_raises(self, test_db):
        held = held_sale_model.create('POS-001', 'ashley', _items(),
                                      subtotal=9.09, gst_amount=0.91, total=10.00)
        held_sale_model.void(held['reference'])
        with pytest.raises(ValueError):
            held_sale_model.void(held['reference'])
