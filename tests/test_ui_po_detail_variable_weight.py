"""
Regression tests for variable-weight Line Total display on the PO detail screen.

Bug: a variable-weight line's Line Total is correctly derived from
received_weight * unit_cost (received_weight is 0 pre-receipt), but editing
Order Qty recomputed it as ordered_qty * unit_cost instead, producing a
misleading dollar figure that then vanished (reverted to $0.00) on the next
table repopulate -- making the Subtotal/GST/Order Total footer flicker and
appear to "not add up" for POs containing variable-weight lines.

Fix: an unreceived variable-weight line shows "-- TBD" instead of "$0.00",
which plugs into the existing "-"-prefixed placeholder convention already
respected by _on_item_changed (skips overwriting it) and _update_total
(excludes it from the subtotal and counts it in the variable-weight footnote).
"""
import pytest
from PyQt6.QtWidgets import QApplication

import models.purchase_order as po_model
import models.po_lines as lines_model


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def po_with_variable_weight_line(test_db, db_conn, supplier_id, dept_id):
    """PO with one variable-weight product (unreceived) and one normal product."""
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit,
             active, unit, variable_weight)
        VALUES ('9999999999999', 'Deli Ham (by weight)', ?, ?,
                8.00, 5.00, 0.0, 1, 'KG', 1, 'KG', 1)
    """, (dept_id, supplier_id))
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit,
             active, unit, variable_weight)
        VALUES ('8888888888888', 'Tinned Beans', ?, ?,
                3.50, 2.00, 10.0, 6, 'EA', 1, 'EA', 0)
    """, (dept_id, supplier_id))
    db_conn.commit()

    po_id = po_model.create(supplier_id, '2026-06-01', '', 'admin')
    lines_model.add(po_id, '9999999999999', 'Deli Ham (by weight)', 1, 27.20)
    lines_model.add(po_id, '8888888888888', 'Tinned Beans', 1, 2.00)
    return po_id


@pytest.fixture()
def po_detail(qtbot, po_with_variable_weight_line):
    from views.purchase_orders.po_detail import PODetail
    widget = PODetail(po_with_variable_weight_line, blank=True)
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestVariableWeightLineTotal:
    def test_unreceived_variable_weight_line_shows_tbd_not_zero(self, po_detail):
        w = po_detail
        lt_item = w.table.item(0, 8)
        assert lt_item.text().startswith("—")
        assert "$0.00" not in lt_item.text()

    def test_normal_line_still_shows_computed_total(self, po_detail):
        w = po_detail
        lt_item = w.table.item(1, 8)
        assert lt_item.text() == "$12.00"   # 1 carton * 6 pack_qty * $2.00

    def test_editing_qty_does_not_overwrite_tbd_placeholder(self, po_detail):
        """Regression: typing an Order Qty must not turn '-- TBD' into a
        qty * unit_cost dollar figure that later reverts to $0.00."""
        w = po_detail
        w.table.blockSignals(False)
        qty_item = w.table.item(0, 6)
        qty_item.setText("5")
        QApplication.processEvents()

        lt_item = w.table.item(0, 8)
        assert lt_item.text().startswith("—")

    def test_subtotal_excludes_tbd_line_and_shows_footnote(self, po_detail):
        w = po_detail
        w._update_total()
        assert w.subtotal_label.text() == "Subtotal (ex GST): $12.00"
        assert "variable weight line" in w.total_label.text()

    def test_received_variable_weight_line_shows_real_total(self, po_detail, db_conn):
        """Once received_weight is recorded, the actual weight-based total shows."""
        db_conn.execute(
            "UPDATE po_lines SET received_weight = 3.0 WHERE barcode = '9999999999999'"
        )
        db_conn.commit()
        w = po_detail
        w.load()
        QApplication.processEvents()

        lt_item = w.table.item(0, 8)
        assert lt_item.text() == "$81.60"   # 3.0 kg * $27.20/kg
