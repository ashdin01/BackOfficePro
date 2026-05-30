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
