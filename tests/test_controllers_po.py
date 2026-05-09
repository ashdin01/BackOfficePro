"""Tests for pure functions in controllers/purchase_order_controller.py."""
import pytest
from datetime import date, timedelta
from controllers.purchase_order_controller import (
    cartons_needed,
    calc_order_units,
    carton_note,
    _days_to_next_delivery,
    get_milk_order_recommendations,
)


class TestCartonsNeeded:
    def test_exact_carton(self):
        assert cartons_needed(12, 12) == 1

    def test_rounds_up_partial_carton(self):
        assert cartons_needed(13, 12) == 2

    def test_single_unit_pack(self):
        assert cartons_needed(5, 1) == 5

    def test_zero_qty_returns_minimum_one(self):
        # Function enforces minimum of 1 carton
        assert cartons_needed(0, 12) == 1

    def test_pack_qty_zero_treated_as_one(self):
        # Invalid pack_qty defaults to 1
        assert cartons_needed(5, 0) == 5

    def test_large_order(self):
        # 120 units, pack of 6 = 20 cartons
        assert cartons_needed(120, 6) == 20

    def test_one_unit_needs_one_carton(self):
        assert cartons_needed(1, 12) == 1


class TestCalcOrderUnits:
    def test_orders_to_reorder_max(self):
        # max=20, on_hand=3 → need 17 more
        assert calc_order_units(20, 5, 3) == 17

    def test_overstock_returns_minimum_one(self):
        # on_hand already above reorder_max → minimum 1
        assert calc_order_units(20, 5, 25) == 1

    def test_falls_back_to_reorder_qty_when_no_max(self):
        # reorder_max=0 → use reorder_qty
        assert calc_order_units(0, 8, 3) == 8

    def test_zero_stock_orders_full_max(self):
        assert calc_order_units(24, 6, 0) == 24

    def test_none_stock_treated_as_zero(self):
        assert calc_order_units(24, 6, None) == 24


class TestCartonNote:
    def test_standard_format(self):
        result = carton_note(12, "EA", "9300000000001")
        assert "12" in result
        assert "EA" in result
        assert "9300000000001" in result

    def test_zero_pack_qty_defaults_to_one(self):
        result = carton_note(0, "EA", "9300000000001")
        assert result.startswith("1 ")

    def test_none_pack_qty_defaults_to_one(self):
        result = carton_note(None, "EA", "9300000000001")
        assert result.startswith("1 ")

    def test_different_pack_units(self):
        result = carton_note(6, "CTN", "9300000000001")
        assert "6" in result
        assert "CTN" in result


# ── _days_to_next_delivery ────────────────────────────────────────────────────

class TestDaysToNextDelivery:
    # Use a known Monday as anchor so weekday arithmetic is deterministic
    _MON = date(2026, 5, 4)   # weekday() == 0

    def test_next_day(self):
        days, d = _days_to_next_delivery('TUE', from_date=self._MON)
        assert days == 1
        assert d == self._MON + timedelta(days=1)

    def test_same_day_returns_seven_not_zero(self):
        days, d = _days_to_next_delivery('MON', from_date=self._MON)
        assert days == 7
        assert d == self._MON + timedelta(days=7)

    def test_friday_from_monday(self):
        days, _ = _days_to_next_delivery('FRI', from_date=self._MON)
        assert days == 4

    def test_multiple_days_picks_nearest(self):
        # MON,THU from Monday → THU is 3 days, MON is 7; nearest is 3
        days, _ = _days_to_next_delivery('MON,THU', from_date=self._MON)
        assert days == 3

    def test_empty_string_defaults_to_three(self):
        days, d = _days_to_next_delivery('', from_date=self._MON)
        assert days == 3
        assert d == self._MON + timedelta(days=3)

    def test_sunday_from_monday(self):
        days, _ = _days_to_next_delivery('SUN', from_date=self._MON)
        assert days == 6

    def test_returns_date_not_string(self):
        _, d = _days_to_next_delivery('WED', from_date=self._MON)
        assert isinstance(d, date)


# ── get_milk_order_recommendations ───────────────────────────────────────────

def _setup_dairy_milk(db_conn, dept_id, supplier_id, delivery_days='TUE,FRI'):
    """Set delivery_days on supplier, add Dairy dept + Milk group + one milk product."""
    db_conn.execute(
        "UPDATE suppliers SET delivery_days=? WHERE id=?",
        (delivery_days, supplier_id)
    )
    # Use the existing DAIRY department from schema defaults
    dairy_id = db_conn.execute(
        "SELECT id FROM departments WHERE code='DAIRY'"
    ).fetchone()['id']

    db_conn.execute("""
        INSERT INTO product_groups (department_id, code, name)
        VALUES (?, 'MLK', 'Milk')
    """, (dairy_id,))
    group_id = db_conn.execute(
        "SELECT id FROM product_groups WHERE code='MLK'"
    ).fetchone()['id']

    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, group_id, supplier_id,
            sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES ('9300000011111', 'MILK 2L', ?, ?, ?, 3.50, 2.00, 10.0, 1, 'EA', 1, 'EA')
    """, (dairy_id, group_id, supplier_id))
    db_conn.commit()
    return group_id


def test_milk_recs_no_delivery_days_returns_empty(test_db, db_conn, dept_id, supplier_id):
    # supplier has delivery_days='' (default)
    result = get_milk_order_recommendations(supplier_id)
    assert result == []


def test_milk_recs_no_milk_products_returns_empty(test_db, db_conn, dept_id, supplier_id):
    db_conn.execute(
        "UPDATE suppliers SET delivery_days='TUE' WHERE id=?", (supplier_id,)
    )
    db_conn.commit()
    result = get_milk_order_recommendations(supplier_id)
    assert result == []


def test_milk_recs_returns_list_with_required_keys(test_db, db_conn, dept_id, supplier_id):
    _setup_dairy_milk(db_conn, dept_id, supplier_id)
    recs = get_milk_order_recommendations(supplier_id)
    assert len(recs) == 1
    r = recs[0]
    for key in ('barcode', 'description', 'cartons', 'avg_daily',
                'cover_days', 'next_delivery', 'has_sales_data'):
        assert key in r


def test_milk_recs_no_sales_data_cartons_minimum_one(test_db, db_conn, dept_id, supplier_id):
    _setup_dairy_milk(db_conn, dept_id, supplier_id)
    recs = get_milk_order_recommendations(supplier_id)
    assert recs[0]['cartons'] >= 1
    assert recs[0]['has_sales_data'] is False


def test_milk_recs_cartons_based_on_avg_sales(test_db, db_conn, dept_id, supplier_id):
    _setup_dairy_milk(db_conn, dept_id, supplier_id, delivery_days='MON,THU,FRI,SAT,SUN,TUE,WED')
    # Map PLU → barcode
    db_conn.execute(
        "INSERT INTO plu_barcode_map (plu, barcode) VALUES (?, ?)",
        (77777, '9300000011111')
    )
    # Add 14 days of sales: 7 units/day → avg_daily = 7
    today = date.today()
    for i in range(1, 15):
        d = (today - timedelta(days=i)).isoformat()
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
            VALUES (?, '77777', 'MILK 2L', 7, 24.50)
        """, (d,))
    db_conn.commit()

    recs = get_milk_order_recommendations(supplier_id)
    assert len(recs) == 1
    r = recs[0]
    assert r['avg_daily'] == 7.0
    assert r['has_sales_data'] is True
    # cover_days = days_ahead + 2 (SAFETY_DAYS), cartons >= 1
    assert r['cartons'] >= 1
    assert r['cover_days'] == r['days_to_delivery'] + 2


def test_milk_recs_high_soh_still_returns_minimum_one(test_db, db_conn, dept_id, supplier_id):
    _setup_dairy_milk(db_conn, dept_id, supplier_id)
    # Set SOH very high so needed_units would be negative
    db_conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity) VALUES ('9300000011111', 9999)
    """)
    db_conn.commit()
    recs = get_milk_order_recommendations(supplier_id)
    assert recs[0]['cartons'] >= 1
