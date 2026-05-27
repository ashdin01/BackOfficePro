"""Tests for models/audit_log.py and its integration with product/supplier/customer/department."""
import pytest
from database.audit_context import set_context
import models.audit_log as audit_model
import models.product as product_model
import models.supplier as supplier_model
import models.customer as customer_model
import models.department as dept_model


@pytest.fixture(autouse=True)
def set_audit_user():
    set_context('testuser', 'UI')


# ── Unit tests for record_changes ─────────────────────────────────────────────

class TestRecordChanges:
    def test_writes_row_for_changed_field(self, test_db, db_conn):
        audit_model.record_changes(
            db_conn, 'product', 'BC001',
            {'sell_price': '2.50'}, {'sell_price': '3.00'}, 'alice'
        )
        db_conn.commit()
        rows = audit_model.get_for_entity('product', 'BC001')
        assert len(rows) == 1
        assert rows[0]['field'] == 'sell_price'
        assert rows[0]['old_value'] == '2.50'
        assert rows[0]['new_value'] == '3.00'
        assert rows[0]['changed_by'] == 'alice'

    def test_skips_unchanged_fields(self, test_db, db_conn):
        audit_model.record_changes(
            db_conn, 'product', 'BC002',
            {'sell_price': '2.50', 'description': 'Same'},
            {'sell_price': '2.50', 'description': 'Same'},
            'alice'
        )
        db_conn.commit()
        assert audit_model.get_for_entity('product', 'BC002') == []

    def test_skips_internal_fields(self, test_db, db_conn):
        audit_model.record_changes(
            db_conn, 'product', 'BC003',
            {'updated_at': '2026-01-01', 'id': '1'},
            {'updated_at': '2026-01-02', 'id': '1'},
            'alice'
        )
        db_conn.commit()
        assert audit_model.get_for_entity('product', 'BC003') == []

    def test_records_multiple_changed_fields(self, test_db, db_conn):
        audit_model.record_changes(
            db_conn, 'supplier', '1',
            {'name': 'Old', 'phone': '0000'},
            {'name': 'New', 'phone': '1111'},
            'bob'
        )
        db_conn.commit()
        rows = audit_model.get_for_entity('supplier', '1')
        fields = {r['field'] for r in rows}
        assert fields == {'name', 'phone'}

    def test_none_old_value_treated_as_empty(self, test_db, db_conn):
        audit_model.record_changes(
            db_conn, 'product', 'BC004',
            {'brand': None}, {'brand': 'Acme'}, 'alice'
        )
        db_conn.commit()
        rows = audit_model.get_for_entity('product', 'BC004')
        assert rows[0]['old_value'] == ''
        assert rows[0]['new_value'] == 'Acme'


# ── get_for_entity / get_recent ───────────────────────────────────────────────

class TestQueries:
    def test_get_for_entity_returns_newest_first(self, test_db, db_conn):
        for price in ['1.00', '2.00', '3.00']:
            audit_model.record_changes(
                db_conn, 'product', 'BCORD',
                {'sell_price': str(float(price) - 1)}, {'sell_price': price}, 'u'
            )
        db_conn.commit()
        rows = audit_model.get_for_entity('product', 'BCORD')
        assert rows[0]['new_value'] == '3.00'

    def test_get_for_entity_filters_by_entity_key(self, test_db, db_conn):
        audit_model.record_changes(db_conn, 'product', 'A', {'x': '1'}, {'x': '2'}, 'u')
        audit_model.record_changes(db_conn, 'product', 'B', {'x': '1'}, {'x': '9'}, 'u')
        db_conn.commit()
        rows = audit_model.get_for_entity('product', 'A')
        assert all(r['entity_key'] == 'A' for r in rows)

    def test_get_recent_returns_all_entities(self, test_db, db_conn):
        audit_model.record_changes(db_conn, 'product',  'P1', {'x': '1'}, {'x': '2'}, 'u')
        audit_model.record_changes(db_conn, 'supplier', 'S1', {'y': '1'}, {'y': '2'}, 'u')
        db_conn.commit()
        entities = {r['entity'] for r in audit_model.get_recent()}
        assert 'product' in entities
        assert 'supplier' in entities


# ── Integration: product model hooks ─────────────────────────────────────────

class TestProductAudit:
    def test_update_records_changed_sell_price(self, test_db, product_barcode, dept_id, supplier_id):
        product_model.update(
            barcode=product_barcode, description='Test Product', brand='',
            plu='', supplier_sku='', pack_qty=1, pack_unit='EA',
            group_id=None, department_id=dept_id, supplier_id=supplier_id,
            unit='EA', sell_price=9.99, cost_price=2.00, tax_rate=10.0,
            reorder_point=0, reorder_max=0,
        )
        rows = audit_model.get_for_entity('product', product_barcode)
        price_change = next((r for r in rows if r['field'] == 'sell_price'), None)
        assert price_change is not None
        assert price_change['new_value'] == '9.99'
        assert price_change['changed_by'] == 'testuser'

    def test_update_no_rows_when_nothing_changes(self, test_db, product_barcode,
                                                  dept_id, supplier_id):
        # Fetch current values and re-save them unchanged
        row = product_model.get_by_barcode(product_barcode)
        product_model.update(
            barcode=product_barcode, description=row['description'], brand=row['brand'] or '',
            plu=row['plu'] or '', supplier_sku=row['supplier_sku'] or '',
            pack_qty=row['pack_qty'], pack_unit=row['pack_unit'],
            group_id=row['group_id'], department_id=row['department_id'],
            supplier_id=row['supplier_id'], unit=row['unit'],
            sell_price=row['sell_price'], cost_price=row['cost_price'],
            tax_rate=row['tax_rate'], reorder_point=row['reorder_point'],
            reorder_max=row['reorder_max'],
        )
        assert audit_model.get_for_entity('product', product_barcode) == []

    def test_update_cost_price_audited(self, test_db, product_barcode):
        product_model.update_cost_price(product_barcode, 5.55)
        rows = audit_model.get_for_entity('product', product_barcode)
        assert any(r['field'] == 'cost_price' and r['new_value'] == '5.55' for r in rows)


# ── Integration: supplier model hook ─────────────────────────────────────────

class TestSupplierAudit:
    def test_update_records_name_change(self, test_db, supplier_id):
        supplier_model.update(
            supplier_id, 'TST', 'Updated Name',
            contact_name='', phone='', account_number='',
            payment_terms='', address='', notes='', active=1,
        )
        rows = audit_model.get_for_entity('supplier', 'Updated Name')
        name_row = next((r for r in rows if r['field'] == 'name'), None)
        assert name_row is not None
        assert name_row['new_value'] == 'Updated Name'
        assert name_row['changed_by'] == 'testuser'


# ── Integration: customer model hook ─────────────────────────────────────────

class TestCustomerAudit:
    def test_update_records_email_change(self, test_db, customer_id):
        customer_model.update(
            customer_id, 'CUST001', 'Test Customer',
            email='new@example.com', payment_terms_days=37,
        )
        rows = audit_model.get_for_entity('customer', 'CUST001')
        email_row = next((r for r in rows if r['field'] == 'email'), None)
        assert email_row is not None
        assert email_row['new_value'] == 'new@example.com'


# ── Integration: department model hook ───────────────────────────────────────

class TestDepartmentAudit:
    def test_update_records_name_change(self, test_db, dept_id):
        dept_model.update(dept_id, 'GROC', 'Grocery Renamed', active=1)
        rows = audit_model.get_for_entity('department', 'GROC')
        name_row = next((r for r in rows if r['field'] == 'name'), None)
        assert name_row is not None
        assert name_row['new_value'] == 'Grocery Renamed'

    def test_unchanged_fields_not_recorded(self, test_db, dept_id):
        # Rename back — only 'name' should appear, not 'code' or 'active'
        dept_model.update(dept_id, 'GROC', 'Grocery Renamed', active=1)
        rows = audit_model.get_for_entity('department', 'GROC')
        fields = {r['field'] for r in rows}
        assert 'code' not in fields
        assert 'active' not in fields


# ── Integration: deactivate hooks ────────────────────────────────────────────

class TestDeactivateAudit:
    def test_deactivate_product_records_active_change(self, test_db, product_barcode):
        product_model.deactivate(product_barcode)
        rows = audit_model.get_for_entity('product', product_barcode)
        active_row = next((r for r in rows if r['field'] == 'active'), None)
        assert active_row is not None
        assert active_row['old_value'] == '1'
        assert active_row['new_value'] == '0'
        assert active_row['changed_by'] == 'testuser'

    def test_deactivate_supplier_records_active_change(self, test_db, supplier_id):
        supplier_model.deactivate(supplier_id)
        rows = audit_model.get_for_entity('supplier', 'Test Supplier')
        active_row = next((r for r in rows if r['field'] == 'active'), None)
        assert active_row is not None
        assert active_row['new_value'] == '0'

    def test_deactivate_customer_records_active_change(self, test_db, customer_id):
        customer_model.deactivate(customer_id)
        rows = audit_model.get_for_entity('customer', 'CUST001')
        active_row = next((r for r in rows if r['field'] == 'active'), None)
        assert active_row is not None
        assert active_row['new_value'] == '0'

    def test_deactivate_department_records_active_change(self, test_db, dept_id):
        dept_model.deactivate(dept_id)
        rows = audit_model.get_for_entity('department', 'GROC')
        active_row = next((r for r in rows if r['field'] == 'active'), None)
        assert active_row is not None
        assert active_row['new_value'] == '0'

    def test_deactivate_already_inactive_no_row(self, test_db, supplier_id):
        supplier_model.deactivate(supplier_id)
        # Deactivating again: old=0, new=0 — no change recorded
        supplier_model.deactivate(supplier_id)
        rows = audit_model.get_for_entity('supplier', 'Test Supplier')
        active_rows = [r for r in rows if r['field'] == 'active']
        assert len(active_rows) == 1
