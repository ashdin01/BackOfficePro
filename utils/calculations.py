"""
Financial calculation utilities.
All PO cost figures are stored ex-GST. GST is calculated forward: amount_ex × rate/100.
"""


def gst_on_ex(amount_ex: float, tax_rate: float) -> float:
    """GST amount given an ex-GST amount and a percentage tax rate (e.g. 10.0)."""
    return amount_ex * (tax_rate / 100.0)


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
        "subtotal": round(subtotal, 2),
        "gst": round(gst_total, 2),
        "order_total": round(subtotal + gst_total, 2),
    }
