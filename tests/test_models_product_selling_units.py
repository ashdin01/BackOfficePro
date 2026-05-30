"""Tests for models/product_selling_units.py."""
import pytest
import sqlite3
import models.product_selling_units as su_model


@pytest.fixture()
def master_bc(db_conn, dept_id, supplier_id):
    """Insert a master product and return its barcode."""
    bc = "9300000000099"
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, active, unit)
        VALUES (?, 'Master Product', ?, ?, 10.00, 5.00, 10.0, 1, 1, 'EA')
    """, (bc, dept_id, supplier_id))
    db_conn.commit()
    return bc


@pytest.fixture()
def selling_unit(master_bc):
    """Insert a selling unit for master_bc and return its id."""
    su_model.add(master_bc, "9300000000100", "1", "500g", 0.5, 5.99)
    units = su_model.get_by_master(master_bc)
    return units[0]['id']


# ── get_master ────────────────────────────────────────────────────────────────

class TestGetMaster:
    def test_returns_none_for_unknown_barcode(self, test_db):
        assert su_model.get_master("0000000000000") is None

    def test_returns_master_for_known_selling_unit(self, master_bc, selling_unit):
        result = su_model.get_master("9300000000100")
        assert result is not None
        assert result['master_barcode'] == master_bc

    def test_returns_label_and_unit_qty(self, master_bc, selling_unit):
        result = su_model.get_master("9300000000100")
        assert result['label'] == "500g"
        assert result['unit_qty'] == 0.5


# ── get_by_master ─────────────────────────────────────────────────────────────

class TestGetByMaster:
    def test_returns_empty_list_when_no_units(self, master_bc):
        assert su_model.get_by_master(master_bc) == []

    def test_returns_all_units_for_master(self, master_bc, selling_unit):
        su_model.add(master_bc, "9300000000101", "2", "1kg", 1.0, 9.99)
        units = su_model.get_by_master(master_bc)
        assert len(units) == 2

    def test_ordered_by_unit_qty(self, master_bc):
        su_model.add(master_bc, "9300000000102", None, "2kg", 2.0, 12.00)
        su_model.add(master_bc, "9300000000103", None, "500g", 0.5, 6.00)
        units = su_model.get_by_master(master_bc)
        qtys = [u['unit_qty'] for u in units]
        assert qtys == sorted(qtys)


# ── add ───────────────────────────────────────────────────────────────────────

class TestAdd:
    def test_add_creates_row(self, master_bc):
        su_model.add(master_bc, "9300000000110", None, "250g", 0.25, 3.49)
        units = su_model.get_by_master(master_bc)
        assert len(units) == 1

    def test_duplicate_barcode_raises(self, master_bc, selling_unit):
        with pytest.raises(Exception):
            su_model.add(master_bc, "9300000000100", None, "500g dup", 0.5, 5.99)

    def test_invalid_master_barcode_raises(self, test_db):
        with pytest.raises(Exception):
            su_model.add("NONEXISTENT", "9300000000199", None, "Label", 1.0, 9.99)


# ── update ────────────────────────────────────────────────────────────────────

class TestUpdate:
    def test_update_changes_label_and_price(self, master_bc, selling_unit):
        su_model.update(selling_unit, "750g", 0.75, None, "9300000000100", 7.49)
        units = su_model.get_by_master(master_bc)
        assert units[0]['label'] == "750g"
        assert units[0]['sell_price'] == 7.49


# ── delete ────────────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_removes_row(self, master_bc, selling_unit):
        su_model.delete(selling_unit)
        assert su_model.get_by_master(master_bc) == []

    def test_delete_nonexistent_is_silent(self, test_db):
        su_model.delete(99999)  # must not raise


# ── get_by_id ─────────────────────────────────────────────────────────────────

class TestGetById:
    def test_returns_none_for_missing_id(self, test_db):
        assert su_model.get_by_id(99999) is None

    def test_returns_dict_for_valid_id(self, master_bc, selling_unit):
        result = su_model.get_by_id(selling_unit)
        assert result is not None
        assert result['label'] == "500g"


# ── find_barcode_by_plu ───────────────────────────────────────────────────────

class TestFindBarcodeByPlu:
    def test_returns_none_for_unknown_plu(self, test_db):
        assert su_model.find_barcode_by_plu("9999") is None

    def test_returns_barcode_for_known_plu(self, master_bc, selling_unit):
        result = su_model.find_barcode_by_plu("1")
        assert result == "9300000000100"
