"""Tests for models/product_suppliers.py."""
import pytest
import models.product_suppliers as ps_model


@pytest.fixture()
def second_supplier_id(db_conn):
    """Insert a second test supplier and return its id."""
    db_conn.execute(
        "INSERT INTO suppliers (code, name) VALUES ('SUP2', 'Second Supplier')"
    )
    db_conn.commit()
    return db_conn.execute(
        "SELECT id FROM suppliers WHERE code='SUP2'"
    ).fetchone()["id"]


class TestGetByBarcode:
    def test_returns_empty_list_when_no_links(self, product_barcode):
        result = ps_model.get_by_barcode(product_barcode)
        assert isinstance(result, list)

    def test_returns_link_after_save(self, product_barcode, supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "SKU-001", "pack_qty": 6, "pack_unit": "EA"}
        ])
        result = ps_model.get_by_barcode(product_barcode)
        assert len(result) == 1
        assert result[0]["supplier_id"] == supplier_id

    def test_default_supplier_listed_first(self, product_barcode, supplier_id, second_supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": second_supplier_id, "is_default": False,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"},
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"},
        ])
        result = ps_model.get_by_barcode(product_barcode)
        assert result[0]["is_default"] == 1
        assert result[0]["supplier_id"] == supplier_id

    def test_includes_supplier_name(self, product_barcode, supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"}
        ])
        result = ps_model.get_by_barcode(product_barcode)
        assert "supplier_name" in result[0].keys()


class TestGetBySupplier:
    def test_returns_empty_for_unlinked_supplier(self, test_db, supplier_id):
        result = ps_model.get_by_supplier(supplier_id)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_returns_product_linked_as_default(self, product_barcode, supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"}
        ])
        result = ps_model.get_by_supplier(supplier_id, default_only=True)
        barcodes = [r["barcode"] for r in result]
        assert product_barcode in barcodes

    def test_default_only_false_includes_non_default(self, product_barcode, supplier_id, second_supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": False,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"},
            {"supplier_id": second_supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"},
        ])
        result = ps_model.get_by_supplier(supplier_id, default_only=False)
        barcodes = [r["barcode"] for r in result]
        assert product_barcode in barcodes

    def test_default_only_true_excludes_non_default(self, product_barcode, supplier_id, second_supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": False,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"},
            {"supplier_id": second_supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"},
        ])
        result = ps_model.get_by_supplier(supplier_id, default_only=True)
        barcodes = [r["barcode"] for r in result]
        assert product_barcode not in barcodes


class TestSaveForBarcode:
    def test_replaces_existing_links(self, product_barcode, supplier_id, second_supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"}
        ])
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": second_supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"}
        ])
        result = ps_model.get_by_barcode(product_barcode)
        assert len(result) == 1
        assert result[0]["supplier_id"] == second_supplier_id

    def test_updates_products_supplier_id_to_default(self, product_barcode, supplier_id, db_conn):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"}
        ])
        row = db_conn.execute(
            "SELECT supplier_id FROM products WHERE barcode=?", (product_barcode,)
        ).fetchone()
        assert row["supplier_id"] == supplier_id

    def test_save_empty_list_clears_all_links(self, product_barcode, supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "", "pack_qty": 1, "pack_unit": "EA"}
        ])
        ps_model.save_for_barcode(product_barcode, [])
        assert ps_model.get_by_barcode(product_barcode) == []

    def test_pack_qty_and_sku_stored_correctly(self, product_barcode, supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "MYSKU-99", "pack_qty": 12, "pack_unit": "CTN"}
        ])
        result = ps_model.get_by_barcode(product_barcode)
        assert result[0]["pack_qty"] == 12
        assert result[0]["pack_unit"] == "CTN"
        assert result[0]["supplier_sku"] == "MYSKU-99"


# ── get_map_for_barcodes / get_for_barcode_and_supplier ─────────────────────────
#
# The "Bonsoy Milk" scenario: a product with a default supplier (Spiral
# Foods) and an alternate supplier (Fords Dairy), each with their own SKU
# and pack size. A PO for the alternate supplier must show *that*
# supplier's SKU/pack, not the default's.

class TestGetMapForBarcodes:
    def test_returns_correct_supplier_specific_row(self, product_barcode, supplier_id, second_supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "SPIRAL-123", "pack_qty": 12, "pack_unit": "CTN"},
            {"supplier_id": second_supplier_id, "is_default": False,
             "supplier_sku": "FORDS-456", "pack_qty": 6, "pack_unit": "CTN"},
        ])

        default_map   = ps_model.get_map_for_barcodes([product_barcode], supplier_id)
        alternate_map = ps_model.get_map_for_barcodes([product_barcode], second_supplier_id)

        assert default_map[product_barcode]["supplier_sku"] == "SPIRAL-123"
        assert default_map[product_barcode]["pack_qty"] == 12
        assert alternate_map[product_barcode]["supplier_sku"] == "FORDS-456"
        assert alternate_map[product_barcode]["pack_qty"] == 6

    def test_barcode_absent_when_not_linked_to_that_supplier(
        self, product_barcode, supplier_id, second_supplier_id
    ):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "SPIRAL-123", "pack_qty": 12, "pack_unit": "CTN"},
        ])
        result = ps_model.get_map_for_barcodes([product_barcode], second_supplier_id)
        assert product_barcode not in result

    def test_empty_barcode_list_returns_empty_map(self, test_db, supplier_id):
        assert ps_model.get_map_for_barcodes([], supplier_id) == {}

    def test_multiple_barcodes_batched_correctly(
        self, db_conn, dept_id, supplier_id, second_supplier_id
    ):
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, supplier_id, active, unit) "
            "VALUES ('9300000000002', 'Second Product', ?, ?, 1, 'EA')",
            (dept_id, supplier_id)
        )
        db_conn.commit()
        ps_model.save_for_barcode('9300000000002', [
            {"supplier_id": second_supplier_id, "is_default": True,
             "supplier_sku": "ALT-SKU", "pack_qty": 3, "pack_unit": "EA"},
        ])

        result = ps_model.get_map_for_barcodes(
            ['9300000000002'], second_supplier_id
        )
        assert result['9300000000002']["supplier_sku"] == "ALT-SKU"


class TestGetForBarcodeAndSupplier:
    def test_returns_none_when_no_link(self, product_barcode, supplier_id):
        assert ps_model.get_for_barcode_and_supplier(product_barcode, supplier_id) is None

    def test_returns_the_matching_row(self, product_barcode, supplier_id):
        ps_model.save_for_barcode(product_barcode, [
            {"supplier_id": supplier_id, "is_default": True,
             "supplier_sku": "SKU-77", "pack_qty": 4, "pack_unit": "EA"},
        ])
        row = ps_model.get_for_barcode_and_supplier(product_barcode, supplier_id)
        assert row["supplier_sku"] == "SKU-77"
        assert row["pack_qty"] == 4
