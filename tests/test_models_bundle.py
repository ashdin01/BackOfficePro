"""Tests for models/bundle.py."""
import pytest
import models.bundle as bundle_model


@pytest.fixture()
def bundle_id(test_db):
    """Insert a test bundle and return its id."""
    return bundle_model.create("Mix & Match", "Any 4 for price", 4, 10.00)


@pytest.fixture()
def eligible_id(bundle_id, product_barcode):
    """Add an eligible item to the test bundle and return its id."""
    return bundle_model.add_eligible(bundle_id, product_barcode, "Test Product", unit_qty=1)


class TestGetAll:
    def test_returns_list(self, test_db):
        assert isinstance(bundle_model.get_all(), list)

    def test_returns_created_bundle(self, bundle_id):
        bundles = bundle_model.get_all()
        ids = [b["id"] for b in bundles]
        assert bundle_id in ids

    def test_active_only_excludes_inactive(self, bundle_id):
        bundle_model.update(bundle_id, "Mix & Match", "desc", 4, 10.00, active=False)
        active = bundle_model.get_all(active_only=True)
        ids = [b["id"] for b in active]
        assert bundle_id not in ids

    def test_active_only_false_includes_inactive(self, bundle_id):
        bundle_model.update(bundle_id, "Mix & Match", "desc", 4, 10.00, active=False)
        all_bundles = bundle_model.get_all(active_only=False)
        ids = [b["id"] for b in all_bundles]
        assert bundle_id in ids


class TestGetById:
    def test_returns_none_for_missing(self, test_db):
        assert bundle_model.get_by_id(9999) is None

    def test_returns_dict_for_existing(self, bundle_id):
        result = bundle_model.get_by_id(bundle_id)
        assert result is not None
        assert isinstance(result, dict)
        assert result["name"] == "Mix & Match"
        assert result["required_qty"] == 4
        assert result["price"] == pytest.approx(10.00)


class TestCreate:
    def test_create_returns_positive_id(self, test_db):
        bid = bundle_model.create("Promo 3 for 2", "", 3, 5.00)
        assert bid > 0

    def test_created_bundle_is_active_by_default(self, test_db):
        bid = bundle_model.create("Active Bundle", "", 2, 8.00)
        row = bundle_model.get_by_id(bid)
        assert row["active"] == 1


class TestUpdate:
    def test_update_name_and_price(self, bundle_id):
        bundle_model.update(bundle_id, "Updated Name", "new desc", 5, 12.50, active=True)
        row = bundle_model.get_by_id(bundle_id)
        assert row["name"] == "Updated Name"
        assert row["price"] == pytest.approx(12.50)
        assert row["required_qty"] == 5

    def test_update_active_false(self, bundle_id):
        bundle_model.update(bundle_id, "Mix & Match", "", 4, 10.00, active=False)
        row = bundle_model.get_by_id(bundle_id)
        assert row["active"] == 0


class TestEligible:
    def test_get_eligible_returns_list(self, bundle_id):
        assert isinstance(bundle_model.get_eligible(bundle_id), list)

    def test_add_eligible_and_retrieve(self, eligible_id, bundle_id, product_barcode):
        items = bundle_model.get_eligible(bundle_id)
        barcodes = [i["barcode"] for i in items]
        assert product_barcode in barcodes

    def test_add_eligible_returns_positive_id(self, bundle_id, product_barcode):
        eid = bundle_model.add_eligible(bundle_id, product_barcode, "Desc", unit_qty=2)
        assert eid > 0

    def test_delete_eligible_removes_item(self, eligible_id, bundle_id, product_barcode):
        bundle_model.delete_eligible(eligible_id)
        items = bundle_model.get_eligible(bundle_id)
        barcodes = [i["barcode"] for i in items]
        assert product_barcode not in barcodes

    def test_add_eligible_duplicate_ignored(self, eligible_id, bundle_id, product_barcode):
        bundle_model.add_eligible(bundle_id, product_barcode, "Desc2", unit_qty=1)
        items = bundle_model.get_eligible(bundle_id)
        assert sum(1 for i in items if i["barcode"] == product_barcode) == 1


class TestResolveBarcode:
    def test_resolve_description_from_products(self, product_barcode):
        desc = bundle_model.resolve_barcode_description(product_barcode)
        assert desc == "Test Product"

    def test_resolve_description_unknown_returns_empty(self, test_db):
        assert bundle_model.resolve_barcode_description("0000000000") == ""

    def test_resolve_unit_qty_non_selling_unit_returns_1(self, product_barcode):
        assert bundle_model.resolve_barcode_unit_qty(product_barcode) == 1

    def test_resolve_unit_qty_selling_unit_returns_qty(self, db_conn, product_barcode):
        su_bc = "9300000099999"
        db_conn.execute("""
            INSERT INTO product_selling_units
                (master_barcode, barcode, label, unit_qty, sell_price, active)
            VALUES (?, ?, '500g', 0.5, 2.00, 1)
        """, (product_barcode, su_bc))
        db_conn.commit()
        assert bundle_model.resolve_barcode_unit_qty(su_bc) == 0  # stored as 0 (< 1 truncates)

    def test_resolve_description_from_selling_unit_label(self, db_conn, product_barcode):
        su_bc = "9300000099998"
        db_conn.execute("""
            INSERT INTO product_selling_units
                (master_barcode, barcode, label, unit_qty, sell_price, active)
            VALUES (?, ?, 'Half Pack', 0.5, 2.00, 1)
        """, (product_barcode, su_bc))
        db_conn.commit()
        # su_bc is NOT in products — resolve_barcode_description should fall through to su table
        desc = bundle_model.resolve_barcode_description(su_bc)
        assert desc == 'Half Pack'
