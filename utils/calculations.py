"""
Shared calculation utilities: financial maths and date range helpers.
All PO cost figures are stored ex-GST. GST is calculated forward: amount_ex × rate/100.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP as _RHU


def round_half_up(value: float, places: int = 2) -> float:
    """Round using commercial half-up rule (3.625 → 3.63, not Python's banker 3.62)."""
    q = Decimal("0." + "0" * places)
    return float(Decimal(str(value)).quantize(q, rounding=_RHU))


def gst_on_ex(amount_ex: float, tax_rate: float) -> float:
    """GST amount given an ex-GST amount and a percentage tax rate (e.g. 10.0)."""
    return amount_ex * (tax_rate / 100.0)


def week_bounds(offset: int = 0) -> tuple[date, date]:
    """Return the Monday–Sunday bounds of a completed week.

    offset=0 → last completed week; offset=1 → two weeks ago.
    """
    today = date.today()
    mon   = today - timedelta(days=today.weekday())
    start = mon - timedelta(weeks=(1 + offset))
    return start, start + timedelta(days=6)


def fy_bounds(year: int | None = None) -> tuple[date, date]:
    """Return the start and end of an Australian financial year (1 Jul → 30 Jun).

    If year is None, uses the current financial year.
    """
    today = date.today()
    if year is None:
        year = today.year if today.month >= 7 else today.year - 1
    return date(year, 7, 1), date(year + 1, 6, 30)


def gross_profit_pct(sell_price: float, cost_price: float, tax_rate: float) -> float | None:
    """Return gross profit as a percentage of sell price, or None if sell_price is zero.

    cost_price is treated as ex-GST; tax_rate is a percentage (e.g. 10.0).
    """
    cost = cost_price * (1 + (tax_rate or 0.0) / 100)
    if sell_price > 0:
        return (1 - cost / sell_price) * 100
    return None


def po_order_totals(lines: list) -> dict:
    """
    Calculate PO subtotal (ex GST), GST, and order total (inc GST).

    Each line dict must contain:
        unit_cost   – cost per unit, ex GST
        ordered_qty – number of cartons / outer packs ordered
        pack_qty    – units per carton (defaults to 1 if missing)
        tax_rate    – percentage, e.g. 10.0 (defaults to 0 if missing)

    Returns a dict: {subtotal, gst, order_total} — all rounded to 2 dp.
    """
    subtotal = 0.0
    gst_total = 0.0
    for line in lines:
        total_units = int(line["ordered_qty"]) * int(line.get("pack_qty", 1))
        line_ex = float(line["unit_cost"]) * total_units
        subtotal += line_ex
        gst_total += gst_on_ex(line_ex, float(line.get("tax_rate", 0.0)))
    return {
        "subtotal": round_half_up(subtotal),
        "gst": round_half_up(gst_total),
        "order_total": round_half_up(subtotal + gst_total),
    }
