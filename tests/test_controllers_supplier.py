"""Tests for supplier_controller."""
import pytest
import controllers.supplier_controller as sup_ctrl


class TestSupplierCRUD:
    def test_get_all_empty_initially(self, test_db):
        assert sup_ctrl.get_all() == []

    def test_create_and_get_by_id(self, test_db):
        sup_ctrl.create('ACME', 'Acme Corp')
        from database.connection import get_connection
        conn = get_connection()
        sid = conn.execute("SELECT id FROM suppliers WHERE code='ACME'").fetchone()['id']
        conn.release()
        result = sup_ctrl.get_by_id(sid)
        assert result['name'] == 'Acme Corp'
        assert result['code'] == 'ACME'

    def test_get_by_id_unknown_returns_none(self, test_db):
        assert sup_ctrl.get_by_id(99999) is None

    def test_get_all_includes_created(self, test_db):
        sup_ctrl.create('SUP1', 'Supplier One')
        sup_ctrl.create('SUP2', 'Supplier Two')
        names = {s['name'] for s in sup_ctrl.get_all()}
        assert 'Supplier One' in names
        assert 'Supplier Two' in names

    def test_update_changes_name(self, test_db, supplier_id):
        sup_ctrl.update(supplier_id, 'TST', 'Updated Name')
        result = sup_ctrl.get_by_id(supplier_id)
        assert result['name'] == 'Updated Name'

    def test_deactivate_removes_from_active_list(self, test_db, supplier_id):
        sup_ctrl.deactivate(supplier_id)
        active_ids = {s['id'] for s in sup_ctrl.get_all(active_only=True)}
        assert supplier_id not in active_ids

    def test_get_all_inactive_false_shows_all(self, test_db, supplier_id):
        sup_ctrl.deactivate(supplier_id)
        all_ids = {s['id'] for s in sup_ctrl.get_all(active_only=False)}
        assert supplier_id in all_ids

    def test_get_products_empty_initially(self, test_db, supplier_id):
        assert sup_ctrl.get_products(supplier_id) == []

    def test_get_products_returns_linked_product(self, test_db, db_conn, supplier_id, product_barcode):
        # product_barcode fixture sets supplier_id on the product but not the junction table
        db_conn.execute("""
            INSERT OR IGNORE INTO product_suppliers (barcode, supplier_id, is_default)
            VALUES (?, ?, 1)
        """, (product_barcode, supplier_id))
        db_conn.commit()
        products = sup_ctrl.get_products(supplier_id, default_only=False)
        barcodes = [p['barcode'] for p in products]
        assert product_barcode in barcodes

    def test_get_order_due_today(self, test_db):
        result = sup_ctrl.get_order_due_today()
        assert isinstance(result, list)
