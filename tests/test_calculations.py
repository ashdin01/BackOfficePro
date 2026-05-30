"""
Tests for utils/calculations.py — the GST and PO totals logic.

These tests exist specifically to guard against the back-calculation bug that was
found in the PO draft screen: unit_cost is stored ex-GST, so GST must be calculated
forward (amount_ex × rate/100), never back-calculated from an inc-GST assumption.
"""
import pytest
from utils.calculations import gst_on_ex, po_order_totals, amount_inc_from_ex, gst_from_inclusive


class TestGstOnEx:
    def test_standard_10_percent(self):
        assert gst_on_ex(100.0, 10.0) == pytest.approx(10.0)

    def test_zero_rate_returns_zero(self):
        assert gst_on_ex(100.0, 0.0) == pytest.approx(0.0)

    def test_partial_amount(self):
        assert gst_on_ex(50.0, 10.0) == pytest.approx(5.0)

    def test_forward_not_back_calculated(self):
        """
        Back-calculation (wrong): gst = amount - amount / (1 + rate/100)
        Forward calculation (correct): gst = amount * rate / 100
        On an ex-GST amount of $100 at 10%, GST must be exactly $10, not $9.09.
        """
        amount_ex = 100.0
        forward = gst_on_ex(amount_ex, 10.0)
        back = amount_ex - (amount_ex / (1 + 10.0 / 100))
        assert forward == pytest.approx(10.0)
        assert back == pytest.approx(9.0909, rel=1e-3)
        assert forward != pytest.approx(back)

    def test_large_amount(self):
        assert gst_on_ex(1_000_000.0, 10.0) == pytest.approx(100_000.0)

    def test_fractional_amount(self):
        assert gst_on_ex(3.33, 10.0) == pytest.approx(0.333)


class TestPoOrderTotals:
    def test_single_taxable_line(self):
        lines = [{"unit_cost": 2.00, "ordered_qty": 10, "pack_qty": 1, "tax_rate": 10.0}]
        r = po_order_totals(lines)
        assert r["subtotal"] == pytest.approx(20.00)
        assert r["gst"] == pytest.approx(2.00)
        assert r["order_total"] == pytest.approx(22.00)

    def test_single_gst_free_line(self):
        lines = [{"unit_cost": 5.00, "ordered_qty": 4, "pack_qty": 1, "tax_rate": 0.0}]
        r = po_order_totals(lines)
        assert r["subtotal"] == pytest.approx(20.00)
        assert r["gst"] == pytest.approx(0.00)
        assert r["order_total"] == pytest.approx(20.00)

    def test_carton_pack_qty_multiplied(self):
        # 2 cartons × 12 pack = 24 units × $1.50 ex = $36.00 ex, $3.60 GST
        lines = [{"unit_cost": 1.50, "ordered_qty": 2, "pack_qty": 12, "tax_rate": 10.0}]
        r = po_order_totals(lines)
        assert r["subtotal"] == pytest.approx(36.00)
        assert r["gst"] == pytest.approx(3.60)
        assert r["order_total"] == pytest.approx(39.60)

    def test_mixed_taxable_and_gst_free(self):
        lines = [
            {"unit_cost": 10.00, "ordered_qty": 5, "pack_qty": 1, "tax_rate": 10.0},
            {"unit_cost": 8.00,  "ordered_qty": 3, "pack_qty": 1, "tax_rate": 0.0},
        ]
        r = po_order_totals(lines)
        assert r["subtotal"] == pytest.approx(74.00)   # 50 + 24
        assert r["gst"] == pytest.approx(5.00)          # 10% of 50 only
        assert r["order_total"] == pytest.approx(79.00)

    def test_empty_lines_returns_zeros(self):
        r = po_order_totals([])
        assert r["subtotal"] == 0.0
        assert r["gst"] == 0.0
        assert r["order_total"] == 0.0

    def test_order_total_equals_subtotal_plus_gst(self):
        lines = [
            {"unit_cost": 7.49, "ordered_qty": 3, "pack_qty": 6, "tax_rate": 10.0},
            {"unit_cost": 2.20, "ordered_qty": 1, "pack_qty": 24, "tax_rate": 0.0},
        ]
        r = po_order_totals(lines)
        assert r["order_total"] == pytest.approx(r["subtotal"] + r["gst"])

    def test_missing_pack_qty_defaults_to_1(self):
        lines = [{"unit_cost": 5.00, "ordered_qty": 3, "tax_rate": 10.0}]
        r = po_order_totals(lines)
        assert r["subtotal"] == pytest.approx(15.00)

    def test_missing_tax_rate_defaults_to_zero(self):
        lines = [{"unit_cost": 5.00, "ordered_qty": 3, "pack_qty": 1}]
        r = po_order_totals(lines)
        assert r["gst"] == pytest.approx(0.00)

    def test_results_rounded_to_two_dp(self):
        # 3 units × $1.334 = $4.002 — should round to $4.00
        lines = [{"unit_cost": 1.334, "ordered_qty": 3, "pack_qty": 1, "tax_rate": 10.0}]
        r = po_order_totals(lines)
        assert r["subtotal"] == round(4.002, 2)
        assert r["gst"] == round(0.4002, 2)


class TestAmountIncFromEx:
    """amount_inc_from_ex: forward-calculate the GST-inclusive price."""

    def test_10_percent(self):
        assert amount_inc_from_ex(100.0, 10.0) == pytest.approx(110.0)

    def test_zero_rate_unchanged(self):
        assert amount_inc_from_ex(50.0, 0.0) == pytest.approx(50.0)

    def test_fractional_amount(self):
        assert amount_inc_from_ex(3.50, 10.0) == pytest.approx(3.85)

    def test_inverse_of_gst_from_inclusive(self):
        """amount_inc_from_ex and gst_from_inclusive must be consistent."""
        ex = 80.0
        inc = amount_inc_from_ex(ex, 10.0)
        assert gst_from_inclusive(inc, 10.0) == pytest.approx(inc - ex)


class TestGstFromInclusive:
    """gst_from_inclusive: extract the GST component from an inc-GST amount.

    This formula is used for freight/charge lines where a supplier quotes the
    total including GST and we need to split out the tax portion.
    """

    def test_10_percent_on_110(self):
        # $110 inc — $10 GST, $100 ex
        assert gst_from_inclusive(110.0, 10.0) == pytest.approx(10.0)

    def test_zero_rate_returns_zero(self):
        assert gst_from_inclusive(110.0, 0.0) == pytest.approx(0.0)

    def test_not_same_as_forward_calculation(self):
        """gst_from_inclusive(110, 10) != gst_on_ex(110, 10): they work on different bases."""
        assert gst_from_inclusive(110.0, 10.0) != pytest.approx(gst_on_ex(110.0, 10.0))

    def test_ex_plus_gst_equals_inc(self):
        inc = 55.0
        gst = gst_from_inclusive(inc, 10.0)
        ex = inc - gst
        assert amount_inc_from_ex(ex, 10.0) == pytest.approx(inc)

    def test_fractional_result(self):
        # $33 inc at 10%: GST = 33 - 33/1.1 = 33 - 30.0̄ = 3.0̄
        assert gst_from_inclusive(33.0, 10.0) == pytest.approx(3.0, rel=1e-5)
