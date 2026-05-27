"""
Canonical helpers for purchase-order type display logic.

  unit_mode (RO, IO)   — ordered_qty / received_qty stored as individual units
  carton_mode (PO, CN) — ordered_qty / received_qty stored as cartons; multiply by pack_qty
  is_return (RO only)  — display values shown as negative (stock leaves store)

Import these three functions anywhere PO quantities or money need displaying.
Previously this logic was duplicated across seven call-sites; any future change
to PO-type semantics only needs to be made here.
"""

_UNIT_MODE_TYPES = frozenset(("RO", "IO"))


def po_unit_mode(po_type: str) -> bool:
    """True for order types that store qty as individual units, not cartons."""
    return po_type in _UNIT_MODE_TYPES


def po_is_return(po_type: str) -> bool:
    """True for Return Orders (RO) — quantities and totals display as negative."""
    return po_type == "RO"


def po_display_qty(po_type: str, stored_qty: int, pack_qty: int) -> int:
    """
    Convert a stored DB quantity to its signed display value.

    RO/IO: stored_qty is already in units — pack_qty is ignored.
    PO/CN: stored_qty is in cartons — multiply by pack_qty for units.
    RO:    result is negated (returns reduce stock on hand).

    Pass pack_qty=1 when displaying the stored value in its native unit without
    carton-to-unit conversion (e.g. showing ordered_qty as-ordered).
    """
    units = stored_qty if po_type in _UNIT_MODE_TYPES else stored_qty * pack_qty
    return -units if po_type == "RO" else units


def fmt_money(v: float) -> str:
    """Format a dollar amount, using -$X.XX notation for negative values."""
    return f"-${abs(v):.2f}" if v < 0 else f"${v:.2f}"
