"""Tests for product_controller."""
import os
import pytest
import controllers.product_controller as product_ctrl
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


# ── Wrapper function coverage ─────────────────────────────────────────────────

class TestProductControllerWrappers:
    def test_get_all_products(self, test_db, product_barcode):
        rows = product_ctrl.get_all_products()
        assert any(r['barcode'] == product_barcode for r in rows)

    def test_get_product_by_barcode(self, test_db, product_barcode):
        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row is not None and row['barcode'] == product_barcode

    def test_get_products_by_barcodes(self, test_db, product_barcode):
        result = product_ctrl.get_products_by_barcodes([product_barcode])
        assert product_barcode in result

    def test_search_products(self, test_db, product_barcode):
        rows = product_ctrl.search_products('Test')
        assert any(r['barcode'] == product_barcode for r in rows)

    def test_get_soh_by_barcode_returns_none_or_dict(self, test_db, product_barcode):
        result = product_ctrl.get_soh_by_barcode(product_barcode)
        assert result is None or isinstance(result, dict)

    def test_get_soh_by_barcodes(self, test_db, product_barcode):
        product_ctrl.adjust_soh(product_barcode, 5, 'RECEIPT')
        result = product_ctrl.get_soh_by_barcodes([product_barcode])
        assert isinstance(result, list) or isinstance(result, dict)

    def test_adjust_soh(self, test_db, product_barcode):
        product_ctrl.adjust_soh(product_barcode, 10, 'RECEIPT', 'PO-001', '', 'test')
        soh = product_ctrl.get_soh_by_barcode(product_barcode)
        assert soh is not None and soh['quantity'] == pytest.approx(10.0)

    def test_add_product(self, test_db, dept_id, supplier_id):
        product_ctrl.add_product(
            '9300000088881', 'New Ctrl Product', dept_id,
            supplier_id=supplier_id, sell_price=5.0, cost_price=3.0, tax_rate=10.0
        )
        assert product_ctrl.get_product_by_barcode('9300000088881') is not None

    def test_update_cost_price(self, test_db, product_barcode):
        product_ctrl.update_cost_price(product_barcode, 3.99)
        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row['cost_price'] == pytest.approx(3.99)

    def test_check_barcode_available_free(self, test_db):
        result = product_ctrl.check_barcode_available('0000000000000')
        assert result is None

    def test_check_barcode_available_taken(self, test_db, product_barcode):
        result = product_ctrl.check_barcode_available(product_barcode)
        assert result is not None

    def test_rename_barcode(self, test_db, product_barcode):
        new_bc = '9300000088882'
        product_ctrl.rename_barcode(product_barcode, new_bc)
        assert product_ctrl.get_product_by_barcode(new_bc) is not None
        assert product_ctrl.get_product_by_barcode(product_barcode) is None

    def test_get_movement_history(self, test_db, product_barcode):
        product_ctrl.adjust_soh(product_barcode, 5, 'RECEIPT')
        rows = product_ctrl.get_movement_history(product_barcode)
        assert isinstance(rows, list) and len(rows) >= 1

    def test_get_recent_adjustments(self, test_db, product_barcode):
        result = product_ctrl.get_recent_adjustments()
        assert isinstance(result, list)

    def test_calculate_gross_profit(self, test_db):
        result = product_ctrl.calculate_gross_profit(10.0, 5.0, 0.0)
        assert result == pytest.approx(50.0)

    def test_calculate_gross_profit_zero_sell(self, test_db):
        assert product_ctrl.calculate_gross_profit(0.0, 5.0, 0.0) is None

    def test_get_all_plu_products(self, test_db):
        assert isinstance(product_ctrl.get_all_plu_products(), list)

    def test_get_duplicate_plu_groups(self, test_db):
        assert isinstance(product_ctrl.get_duplicate_plu_groups(), list)

    def test_get_plu_map_conflicts(self, test_db):
        assert isinstance(product_ctrl.get_plu_map_conflicts(), list)

    def test_set_product_plu(self, test_db, product_barcode):
        product_ctrl.set_product_plu(product_barcode, '999')
        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row['plu'] == '999'

    def test_sync_plu_map(self, test_db, product_barcode):
        product_ctrl.sync_plu_map(product_barcode, '888')

    def test_delete_plu_map_entry(self, test_db, product_barcode, db_conn):
        db_conn.execute(
            "INSERT OR IGNORE INTO plu_barcode_map (plu, barcode) VALUES (777, ?)",
            (product_barcode,)
        )
        db_conn.commit()
        product_ctrl.delete_plu_map_entry(777)

    def test_get_aliases_empty(self, test_db, product_barcode):
        assert product_ctrl.get_aliases(product_barcode) == []

    def test_add_and_delete_alias(self, test_db, product_barcode):
        product_ctrl.add_alias('9300000000099', product_barcode, 'alias')
        aliases = product_ctrl.get_aliases(product_barcode)
        assert len(aliases) == 1
        product_ctrl.delete_alias(aliases[0]['id'])
        assert product_ctrl.get_aliases(product_barcode) == []

    def test_get_all_for_pos(self, test_db, product_barcode):
        rows = product_ctrl.get_all_for_pos()
        assert isinstance(rows, list)

    def test_get_product_for_pos_known(self, test_db, product_barcode):
        result = product_ctrl.get_product_for_pos(product_barcode)
        assert result is not None

    def test_get_product_for_pos_unknown(self, test_db):
        assert product_ctrl.get_product_for_pos('0000000000000') is None

    def test_get_product_by_plu_none_when_not_mapped(self, test_db):
        assert product_ctrl.get_product_by_plu(99999) is None

    def test_get_selling_unit_master_none_for_normal(self, test_db, product_barcode):
        result = product_ctrl.get_selling_unit_master(product_barcode)
        assert result is None

    def test_get_selling_units_empty(self, test_db, product_barcode):
        assert product_ctrl.get_selling_units(product_barcode) == []

    def test_add_and_get_and_delete_selling_unit(self, test_db, product_barcode):
        product_ctrl.add_selling_unit(product_barcode, '9300000099777', '999', 'Half', 0.5, 2.00)
        units = product_ctrl.get_selling_units(product_barcode)
        assert len(units) == 1
        su = product_ctrl.get_selling_unit_by_id(units[0]['id'])
        assert su is not None
        product_ctrl.update_selling_unit(su['id'], 'Half kg', 0.5, '999', '9300000099777', 2.00)
        product_ctrl.delete_selling_unit(su['id'])
        assert product_ctrl.get_selling_units(product_barcode) == []

    def test_find_product_image_none_when_missing(self, test_db, product_barcode):
        result = product_ctrl.find_product_image(product_barcode)
        assert result is None

    def test_prepare_image_destination_creates_dir(self, test_db, product_barcode, tmp_path, monkeypatch):
        import config.settings as cfg
        monkeypatch.setattr(cfg, 'DATA_DIR', str(tmp_path))
        path = product_ctrl.prepare_image_destination(product_barcode)
        assert path.endswith('.jpg')
        assert os.path.isdir(os.path.dirname(path))

    def test_delete_product_image_no_op_when_missing(self, test_db, product_barcode):
        product_ctrl.delete_product_image(product_barcode)  # must not raise

    def test_get_product_suppliers_empty(self, test_db, product_barcode):
        rows = product_ctrl.get_product_suppliers(product_barcode)
        assert isinstance(rows, list)

    def test_save_product_updates_price(self, test_db, product_barcode, dept_id, supplier_id):
        product_ctrl.save_product(
            barcode=product_barcode, description='Test Product', brand='', plu='',
            supplier_sku='', pack_qty=1, pack_unit='EA', group_id=None,
            department_id=dept_id, supplier_id=supplier_id, unit='EA',
            sell_price=9.99, cost_price=5.00, tax_rate=10.0,
            reorder_point=0, reorder_max=0, variable_weight=0, expected=1,
            active=1, auto_reorder=0, product_suppliers=[],
        )
        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row['sell_price'] == pytest.approx(9.99)

    def test_save_product_blank_description_raises(self, test_db, product_barcode, dept_id, supplier_id):
        with pytest.raises(ValueError, match="Description is required"):
            product_ctrl.save_product(
                barcode=product_barcode, description='   ', brand='', plu='',
                supplier_sku='', pack_qty=1, pack_unit='EA', group_id=None,
                department_id=dept_id, supplier_id=supplier_id, unit='EA',
                sell_price=9.99, cost_price=5.00, tax_rate=10.0,
                reorder_point=0, reorder_max=0, variable_weight=0, expected=1,
                active=1, auto_reorder=0, product_suppliers=[],
            )

    def test_add_product_blank_description_raises(self, test_db, dept_id, supplier_id):
        with pytest.raises(ValueError, match="Description is required"):
            product_ctrl.add_product(
                '9300000088883', '  ', dept_id,
                supplier_id=supplier_id, sell_price=5.0, cost_price=3.0, tax_rate=10.0
            )

    def test_set_online_available_toggles_flag(self, test_db, product_barcode):
        product_ctrl.set_online_available(product_barcode, True)
        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row['online_available'] == 1

        product_ctrl.set_online_available(product_barcode, False)
        row = product_ctrl.get_product_by_barcode(product_barcode)
        assert row['online_available'] == 0

    def test_get_product_suppliers_returns_junction_rows(
        self, test_db, product_barcode, dept_id, supplier_id
    ):
        product_ctrl.save_product(
            barcode=product_barcode, description='Test Product', brand='', plu='',
            supplier_sku='', pack_qty=1, pack_unit='EA', group_id=None,
            department_id=dept_id, supplier_id=supplier_id, unit='EA',
            sell_price=9.99, cost_price=5.00, tax_rate=10.0,
            reorder_point=0, reorder_max=0, variable_weight=0, expected=1,
            active=1, auto_reorder=0,
            product_suppliers=[{
                'supplier_id': supplier_id, 'is_default': True,
                'supplier_sku': 'SKU-1', 'pack_qty': 6, 'pack_unit': 'CTN',
            }],
        )
        rows = product_ctrl.get_product_suppliers(product_barcode)
        assert len(rows) == 1
        assert rows[0]['supplier_id'] == supplier_id
        assert rows[0]['is_default'] is True
        assert rows[0]['supplier_sku'] == 'SKU-1'
        assert rows[0]['pack_qty'] == 6

    def test_get_product_suppliers_fallback_when_no_junction_rows(
        self, test_db, product_barcode, supplier_id
    ):
        rows = product_ctrl.get_product_suppliers(
            product_barcode, fallback_supplier_id=supplier_id,
            fallback_sku='FBSKU', fallback_pack_qty=3, fallback_pack_unit='CTN',
        )
        assert len(rows) == 1
        assert rows[0]['supplier_id'] == supplier_id
        assert rows[0]['is_default'] is True
        assert rows[0]['supplier_sku'] == 'FBSKU'
        assert rows[0]['pack_qty'] == 3

    def test_find_product_image_returns_path_when_present(
        self, test_db, product_barcode, tmp_path, monkeypatch
    ):
        import config.settings as cfg
        monkeypatch.setattr(cfg, 'DATA_DIR', str(tmp_path))
        img_dir = tmp_path / 'images'
        img_dir.mkdir()
        img_path = img_dir / f'{product_barcode}.jpg'
        img_path.write_bytes(b'fake-jpg-bytes')

        result = product_ctrl.find_product_image(product_barcode)
        assert result == str(img_path)

    def test_prepare_image_destination_removes_alternate_extension_file(
        self, test_db, product_barcode, tmp_path, monkeypatch
    ):
        import config.settings as cfg
        monkeypatch.setattr(cfg, 'DATA_DIR', str(tmp_path))
        img_dir = tmp_path / 'images'
        img_dir.mkdir()
        old_png = img_dir / f'{product_barcode}.png'
        old_png.write_bytes(b'old-png-bytes')

        path = product_ctrl.prepare_image_destination(product_barcode)

        assert not old_png.exists()
        assert path.endswith('.jpg')

    def test_delete_product_image_removes_existing_file(
        self, test_db, product_barcode, tmp_path, monkeypatch
    ):
        import config.settings as cfg
        monkeypatch.setattr(cfg, 'DATA_DIR', str(tmp_path))
        img_dir = tmp_path / 'images'
        img_dir.mkdir()
        img_path = img_dir / f'{product_barcode}.jpg'
        img_path.write_bytes(b'fake-jpg-bytes')

        product_ctrl.delete_product_image(product_barcode)

        assert not img_path.exists()

    def test_get_product_by_plu_found_via_plu_barcode_map(
        self, test_db, db_conn, product_barcode
    ):
        db_conn.execute(
            "INSERT INTO plu_barcode_map (plu, barcode) VALUES (5000, ?)", (product_barcode,)
        )
        db_conn.commit()
        result = product_ctrl.get_product_by_plu(5000)
        assert result is not None
        assert result['barcode'] == product_barcode

    def test_get_product_by_plu_found_via_products_plu_column(
        self, test_db, product_barcode
    ):
        product_ctrl.set_product_plu(product_barcode, '6000')
        result = product_ctrl.get_product_by_plu(6000)
        assert result is not None
        assert result['barcode'] == product_barcode

    def test_get_product_by_plu_found_via_selling_unit_plu(
        self, test_db, product_barcode
    ):
        su_barcode = '9300000099778'
        product_ctrl.add_selling_unit(product_barcode, su_barcode, '7000', 'Half', 0.5, 2.00)
        result = product_ctrl.get_product_by_plu(7000)
        assert result is not None
        assert result['barcode'] == su_barcode

    def test_get_product_for_pos_selling_unit_branch(self, test_db, product_barcode):
        su_barcode = '9300000099779'
        product_ctrl.add_selling_unit(product_barcode, su_barcode, '7001', 'Half', 0.5, 2.00)
        product_ctrl.adjust_soh(product_barcode, 4, 'RECEIPT')

        result = product_ctrl.get_product_for_pos(su_barcode)

        assert result is not None
        assert result['master_barcode'] == product_barcode
        assert result['soh_qty'] == 8  # 4 units / 0.5 unit_qty per selling unit
