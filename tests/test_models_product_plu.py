"""Tests for models/product_plu.py (split from models/product.py in v7 refactor)."""
import pytest
import models.product_plu as plu_model


class TestGetAllPlu:
    def test_empty_when_no_plu_assigned(self, test_db, product_barcode):
        assert plu_model.get_all_plu() == []

    def test_returns_product_after_plu_set(self, test_db, product_barcode):
        plu_model.set_plu(product_barcode, '42')
        rows = plu_model.get_all_plu()
        assert any(r['barcode'] == product_barcode for r in rows)

    def test_ordered_numerically(self, test_db, db_conn, dept_id, supplier_id):
        for bc, plu in [('BC001', '10'), ('BC002', '2'), ('BC003', '1')]:
            db_conn.execute("""
                INSERT INTO products (barcode, description, department_id, supplier_id,
                    sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
                VALUES (?, 'P', ?, ?, 1, 0.5, 10, 1, 'EA', 1, 'EA')
            """, (bc, dept_id, supplier_id))
        db_conn.commit()
        for bc, plu in [('BC001', '10'), ('BC002', '2'), ('BC003', '1')]:
            plu_model.set_plu(bc, plu)
        rows = plu_model.get_all_plu()
        plus = [r['plu'] for r in rows]
        assert plus == sorted(plus, key=lambda p: int(p))


class TestSetPlu:
    def test_set_plu_assigns_value(self, test_db, product_barcode):
        plu_model.set_plu(product_barcode, '99')
        rows = plu_model.get_all_plu()
        match = next((r for r in rows if r['barcode'] == product_barcode), None)
        assert match is not None
        assert match['plu'] == '99'

    def test_clear_plu_with_empty_string(self, test_db, product_barcode):
        plu_model.set_plu(product_barcode, '50')
        plu_model.set_plu(product_barcode, '')
        assert plu_model.get_all_plu() == []

    def test_duplicate_plu_raises_value_error(self, test_db, db_conn, dept_id, supplier_id, product_barcode):
        db_conn.execute("""
            INSERT INTO products (barcode, description, department_id, supplier_id,
                sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
            VALUES ('BC_OTHER', 'Other', ?, ?, 1, 0.5, 10, 1, 'EA', 1, 'EA')
        """, (dept_id, supplier_id))
        db_conn.commit()
        plu_model.set_plu(product_barcode, '7')
        with pytest.raises(ValueError, match="7"):
            plu_model.set_plu('BC_OTHER', '7')

    def test_reassign_own_plu_does_not_raise(self, test_db, product_barcode):
        plu_model.set_plu(product_barcode, '11')
        plu_model.set_plu(product_barcode, '11')  # same barcode, same PLU — OK


class TestFindBarcodeByPlu:
    def test_returns_none_when_not_found(self, test_db):
        assert plu_model.find_barcode_by_plu('999') is None

    def test_returns_barcode_after_assignment(self, test_db, product_barcode):
        plu_model.set_plu(product_barcode, '55')
        assert plu_model.find_barcode_by_plu('55') == product_barcode

    def test_inactive_product_not_returned(self, test_db, db_conn, product_barcode):
        plu_model.set_plu(product_barcode, '60')
        db_conn.execute("UPDATE products SET active=0 WHERE barcode=?", (product_barcode,))
        db_conn.commit()
        assert plu_model.find_barcode_by_plu('60') is None


class TestDuplicatePluGroups:
    def test_no_duplicates_initially(self, test_db, product_barcode):
        plu_model.set_plu(product_barcode, '1')
        assert plu_model.get_duplicate_plu_groups() == []

    def test_detects_shared_plu(self, test_db, db_conn, dept_id, supplier_id, product_barcode):
        db_conn.execute("""
            INSERT INTO products (barcode, description, department_id, supplier_id,
                sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
            VALUES ('DUP_BC', 'Dup', ?, ?, 1, 0.5, 10, 1, 'EA', 1, 'EA')
        """, (dept_id, supplier_id))
        db_conn.commit()
        db_conn.execute("UPDATE products SET plu='77' WHERE barcode=?", (product_barcode,))
        db_conn.execute("UPDATE products SET plu='77' WHERE barcode='DUP_BC'")
        db_conn.commit()
        groups = plu_model.get_duplicate_plu_groups()
        assert len(groups) == 2
        assert all(r['plu'] == '77' for r in groups)


class TestGetPluMapConflicts:
    def test_returns_empty_when_no_conflicts(self, test_db):
        assert plu_model.get_plu_map_conflicts() == []

    def test_detects_conflict(self, test_db, product_barcode, db_conn):
        # Set product plu to '100', plu_barcode_map to plu=200
        db_conn.execute(
            "UPDATE products SET plu='100' WHERE barcode=?", (product_barcode,)
        )
        db_conn.execute(
            "INSERT OR REPLACE INTO plu_barcode_map (plu, barcode) VALUES (200, ?)",
            (product_barcode,)
        )
        db_conn.commit()
        conflicts = plu_model.get_plu_map_conflicts()
        assert any(r['barcode'] == product_barcode for r in conflicts)
