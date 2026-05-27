"""Tests for product_controller.get_stock_on_order_detail."""
import pytest
from controllers.product_controller import get_stock_on_order, get_stock_on_order_detail


@pytest.fixture()
def two_open_pos(db_conn, product_barcode, supplier_id):
    """Two open POs with lines for product_barcode; returns barcode and po ids."""
    bc = product_barcode  # pack_qty=1 on product

    db_conn.execute("""
        INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
        VALUES ('PO-DET-001', ?, 'SENT', 'PO')
    """, (supplier_id,))
    po1_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    db_conn.execute("""
        INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty, unit_cost)
        VALUES (?, ?, 'Test Product', 5, 0, 2.00)
    """, (po1_id, bc))

    db_conn.execute("""
        INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
        VALUES ('PO-DET-002', ?, 'DRAFT', 'PO')
    """, (supplier_id,))
    po2_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    db_conn.execute("""
        INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty, unit_cost)
        VALUES (?, ?, 'Test Product', 3, 1, 2.00)
    """, (po2_id, bc))

    db_conn.commit()
    return {'barcode': bc, 'po1_id': po1_id, 'po2_id': po2_id}


class TestGetStockOnOrderDetail:
    def test_returns_one_row_per_open_po(self, test_db, two_open_pos):
        rows = get_stock_on_order_detail(two_open_pos['barcode'])
        assert len(rows) == 2

    def test_row_fields_present(self, test_db, two_open_pos):
        rows = get_stock_on_order_detail(two_open_pos['barcode'])
        for row in rows:
            assert 'po_number' in row
            assert 'supplier_name' in row
            assert 'qty_units' in row
            assert 'status' in row
            assert 'po_type' in row

    def test_qty_units_correct(self, test_db, two_open_pos):
        rows = get_stock_on_order_detail(two_open_pos['barcode'])
        po_map = {r['po_number']: r for r in rows}
        # PO-DET-001: 5 ordered, 0 received → 5 units
        assert po_map['PO-DET-001']['qty_units'] == 5
        # PO-DET-002: 3 ordered, 1 received → 2 units
        assert po_map['PO-DET-002']['qty_units'] == 2

    def test_supplier_name_populated(self, test_db, two_open_pos):
        rows = get_stock_on_order_detail(two_open_pos['barcode'])
        for row in rows:
            assert row['supplier_name'] == 'Test Supplier'

    def test_status_values(self, test_db, two_open_pos):
        rows = get_stock_on_order_detail(two_open_pos['barcode'])
        po_map = {r['po_number']: r for r in rows}
        assert po_map['PO-DET-001']['status'] == 'SENT'
        assert po_map['PO-DET-002']['status'] == 'DRAFT'

    def test_ordered_by_po_number(self, test_db, two_open_pos):
        rows = get_stock_on_order_detail(two_open_pos['barcode'])
        po_numbers = [r['po_number'] for r in rows]
        assert po_numbers == sorted(po_numbers)

    def test_no_open_pos_returns_empty(self, test_db, product_barcode):
        rows = get_stock_on_order_detail(product_barcode)
        assert rows == []

    def test_closed_po_excluded(self, test_db, db_conn, product_barcode, supplier_id):
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('PO-CLOSED-001', ?, 'CLOSED', 'PO')
        """, (supplier_id,))
        po_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty, unit_cost)
            VALUES (?, ?, 'Test Product', 10, 0, 2.00)
        """, (po_id, product_barcode))
        db_conn.commit()
        rows = get_stock_on_order_detail(product_barcode)
        assert rows == []

    def test_fully_received_line_excluded(self, test_db, db_conn, product_barcode, supplier_id):
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('PO-FULL-001', ?, 'PARTIAL', 'PO')
        """, (supplier_id,))
        po_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty, unit_cost)
            VALUES (?, ?, 'Test Product', 5, 5, 2.00)
        """, (po_id, product_barcode))
        db_conn.commit()
        rows = get_stock_on_order_detail(product_barcode)
        assert rows == []

    def test_detail_total_matches_get_stock_on_order(self, test_db, two_open_pos):
        barcode = two_open_pos['barcode']
        rows = get_stock_on_order_detail(barcode)
        total = sum(r['qty_units'] for r in rows)
        assert total == get_stock_on_order(barcode)

    def test_pack_qty_multiplied(self, test_db, db_conn, dept_id, supplier_id):
        bc = '9300000000099'
        db_conn.execute("""
            INSERT INTO products
                (barcode, description, department_id, supplier_id,
                 sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
            VALUES (?, 'Pack Product', ?, ?, 5.00, 3.00, 10.0, 6, 'EA', 1, 'EA')
        """, (bc, dept_id, supplier_id))
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('PO-PACK-001', ?, 'SENT', 'PO')
        """, (supplier_id,))
        po_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty, unit_cost)
            VALUES (?, ?, 'Pack Product', 4, 0, 3.00)
        """, (po_id, bc))
        db_conn.commit()
        rows = get_stock_on_order_detail(bc)
        assert len(rows) == 1
        assert rows[0]['qty_units'] == 24  # 4 cartons × 6 units

    def test_ro_type_uses_units_not_cartons(self, test_db, db_conn, dept_id, supplier_id):
        """RO ordered_qty is already in units — must NOT be multiplied by pack_qty."""
        bc = '9300000000098'
        db_conn.execute("""
            INSERT INTO products
                (barcode, description, department_id, supplier_id,
                 sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
            VALUES (?, 'RO Product', ?, ?, 5.00, 3.00, 10.0, 6, 'EA', 1, 'EA')
        """, (bc, dept_id, supplier_id))
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('RO-DET-001', ?, 'SENT', 'RO')
        """, (supplier_id,))
        po_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # ordered_qty=3 means 3 units (not 3 cartons) for RO type
        db_conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty, unit_cost)
            VALUES (?, ?, 'RO Product', 3, 0, 3.00)
        """, (po_id, bc))
        db_conn.commit()
        rows = get_stock_on_order_detail(bc)
        assert len(rows) == 1
        assert rows[0]['qty_units'] == 3  # NOT 3 × 6 = 18
        assert get_stock_on_order(bc) == 3

    def test_io_type_uses_units_not_cartons(self, test_db, db_conn, dept_id, supplier_id):
        """IO ordered_qty is already in units — must NOT be multiplied by pack_qty."""
        bc = '9300000000097'
        db_conn.execute("""
            INSERT INTO products
                (barcode, description, department_id, supplier_id,
                 sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
            VALUES (?, 'IO Product', ?, ?, 5.00, 3.00, 10.0, 12, 'EA', 1, 'EA')
        """, (bc, dept_id, supplier_id))
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('IO-DET-001', ?, 'DRAFT', 'IO')
        """, (supplier_id,))
        po_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.execute("""
            INSERT INTO po_lines (po_id, barcode, description, ordered_qty, received_qty, unit_cost)
            VALUES (?, ?, 'IO Product', 7, 2, 3.00)
        """, (po_id, bc))
        db_conn.commit()
        rows = get_stock_on_order_detail(bc)
        assert len(rows) == 1
        assert rows[0]['qty_units'] == 5  # 7 - 2 = 5 units, NOT (7-2) × 12 = 60
