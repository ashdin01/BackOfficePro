"""
Computed display data for the PO history view.

compute_po_history_data() is the single source of truth for how received
quantities, line totals, and GST are calculated for any PO type.
POHistory._load_lines, ._export_csv, and ._export_pdf all call this once
and iterate the result; none of them duplicate the calculation logic.
"""
import dataclasses
import controllers.purchase_order_controller as po_ctrl
import controllers.product_controller as product_ctrl
from utils.po_type_helpers import po_unit_mode, po_is_return, po_display_qty
from utils.calculations import round_half_up


@dataclasses.dataclass
class LineData:
    barcode: str
    description: str
    pack_str: str
    tax_rate: float
    cost: float
    recv_raw: int       # raw DB received_qty — needed for CSV carton column
    recv_units: int     # signed display units (negative for RO)
    ordered_qty_raw: int  # raw DB ordered_qty — needed for CSV carton column
    ordered_disp: int   # signed display value (negative for RO)
    line_ex: float
    line_gst: float
    line_inc: float
    is_promo: bool


@dataclasses.dataclass
class ChargeData:
    description: str
    tax_r: float
    amt_ex: float
    amt_inc: float


@dataclasses.dataclass
class POHistoryData:
    po_type: str
    unit_mode: bool
    is_return: bool
    lines: list         # list[LineData]
    charges: list       # list[ChargeData]
    grand_ex: float     # all lines + charges, ex. GST
    grand_gst: float
    grand_inc: float


def compute_po_history_data(po_id: int, po=None) -> POHistoryData:
    """
    Fetch and calculate display data for a PO.

    Pass a pre-fetched po row to avoid a redundant DB query (e.g. when the
    caller already holds it from _build_ui).  lines and charges are always
    fetched here so callers do not need to manage those.
    """
    if po is None:
        po = po_ctrl.get_po_by_id(po_id)

    lines   = po_ctrl.get_po_lines(po_id)
    charges = po_ctrl.get_po_charges(po_id)

    _po_type  = po['po_type'] or 'PO'
    unit_mode = po_unit_mode(_po_type)
    is_return = po_is_return(_po_type)

    line_results = []
    total_ex = total_gst = 0.0

    for line in lines:
        if line['is_note']:
            continue
        product   = product_ctrl.get_product_by_barcode(line['barcode'])
        pack_qty  = int(product['pack_qty'])  if product and product['pack_qty']  else 1
        pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
        tax_rate  = float(product['tax_rate']) if product and product['tax_rate'] else 0.0
        pack_str  = f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit

        cost         = float(line['actual_cost'] or line['unit_cost'] or 0)
        recv_raw     = int(line['received_qty'] or 0)
        recv_units   = po_display_qty(_po_type, recv_raw, pack_qty)
        ordered_disp = po_display_qty(_po_type, int(line['ordered_qty']), 1)
        line_ex  = round_half_up(recv_units * cost)
        line_gst = round_half_up(abs(line_ex) * tax_rate / 100) * (-1 if is_return else 1)
        line_inc = round_half_up(line_ex + line_gst)

        total_ex  += line_ex
        total_gst += line_gst

        line_results.append(LineData(
            barcode=line['barcode'],
            description=line['description'],
            pack_str=pack_str,
            tax_rate=tax_rate,
            cost=cost,
            recv_raw=recv_raw,
            recv_units=recv_units,
            ordered_qty_raw=int(line['ordered_qty']),
            ordered_disp=ordered_disp,
            line_ex=line_ex,
            line_gst=line_gst,
            line_inc=line_inc,
            is_promo=bool(line['is_promo']),
        ))

    charge_results = []
    charge_ex = charge_gst = 0.0
    for c in charges:
        amt_inc = float(c['amount_inc_tax'])
        tax_r   = float(c['tax_rate'])
        amt_ex  = round_half_up(amt_inc / (1 + tax_r / 100)) if tax_r > 0 else amt_inc
        charge_ex  += amt_ex
        charge_gst += round_half_up(amt_inc - amt_ex)
        charge_results.append(ChargeData(
            description=c['description'],
            tax_r=tax_r,
            amt_ex=amt_ex,
            amt_inc=amt_inc,
        ))

    grand_ex  = round_half_up(total_ex  + charge_ex)
    grand_gst = round_half_up(total_gst + charge_gst)
    grand_inc = round_half_up(grand_ex  + grand_gst)

    return POHistoryData(
        po_type=_po_type,
        unit_mode=unit_mode,
        is_return=is_return,
        lines=line_results,
        charges=charge_results,
        grand_ex=grand_ex,
        grand_gst=grand_gst,
        grand_inc=grand_inc,
    )
