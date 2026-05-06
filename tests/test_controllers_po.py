"""Tests for pure functions in controllers/purchase_order_controller.py."""
import pytest
from controllers.purchase_order_controller import (
    cartons_needed,
    calc_order_units,
    carton_note,
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
