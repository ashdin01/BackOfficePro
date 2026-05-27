"""Tests for bundle_controller."""
import pytest
import controllers.bundle_controller as bundle_ctrl


@pytest.fixture()
def bundle_id(test_db):
    return bundle_ctrl.create('Mixed Case', 'Any 4 for $10', required_qty=4, price=10.00)


class TestBundleCRUD:
    def test_get_all_empty_initially(self, test_db):
        assert bundle_ctrl.get_all() == []

    def test_create_returns_int_id(self, test_db):
        bid = bundle_ctrl.create('Deal', '', 4, 9.99)
        assert isinstance(bid, int) and bid > 0

    def test_get_by_id_returns_correct_record(self, test_db, bundle_id):
        result = bundle_ctrl.get_by_id(bundle_id)
        assert result['name'] == 'Mixed Case'
        assert result['required_qty'] == 4
        assert result['price'] == pytest.approx(10.00)

    def test_get_by_id_unknown_returns_none(self, test_db):
        assert bundle_ctrl.get_by_id(99999) is None

    def test_get_all_includes_created(self, test_db, bundle_id):
        bundles = bundle_ctrl.get_all()
        assert any(b['id'] == bundle_id for b in bundles)

    def test_get_all_active_only_filters_inactive(self, test_db, bundle_id):
        bundle_ctrl.update(bundle_id, 'Mixed Case', '', 4, 10.00, active=False)
        assert bundle_ctrl.get_all(active_only=True) == []

    def test_update_changes_price(self, test_db, bundle_id):
        bundle_ctrl.update(bundle_id, 'Mixed Case', '', 4, 12.50, active=True)
        assert bundle_ctrl.get_by_id(bundle_id)['price'] == pytest.approx(12.50)


class TestBundleEligible:
    def test_get_eligible_empty_for_new_bundle(self, test_db, bundle_id):
        assert bundle_ctrl.get_eligible(bundle_id) == []

    def test_add_and_get_eligible(self, test_db, bundle_id, product_barcode):
        bundle_ctrl.add_eligible(bundle_id, product_barcode, 'Test Product', unit_qty=1)
        items = bundle_ctrl.get_eligible(bundle_id)
        assert len(items) == 1
        assert items[0]['barcode'] == product_barcode

    def test_delete_eligible(self, test_db, bundle_id, product_barcode):
        bundle_ctrl.add_eligible(bundle_id, product_barcode, 'Test Product')
        eid = bundle_ctrl.get_eligible(bundle_id)[0]['id']
        bundle_ctrl.delete_eligible(eid)
        assert bundle_ctrl.get_eligible(bundle_id) == []

    def test_update_eligible_unit_qty(self, test_db, bundle_id, product_barcode):
        bundle_ctrl.add_eligible(bundle_id, product_barcode, 'Test Product', unit_qty=1)
        eid = bundle_ctrl.get_eligible(bundle_id)[0]['id']
        bundle_ctrl.update_eligible_unit_qty(eid, 2)
        assert bundle_ctrl.get_eligible(bundle_id)[0]['unit_qty'] == 2

    def test_resolve_barcode_description(self, test_db, product_barcode):
        desc = bundle_ctrl.resolve_barcode_description(product_barcode)
        assert desc == 'Test Product'

    def test_resolve_unknown_barcode_returns_empty(self, test_db):
        assert bundle_ctrl.resolve_barcode_description('9999999') == ''
