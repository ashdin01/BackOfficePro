"""Widget regression tests for the per-supplier SKU/pack size fix — the
"Bonsoy Milk" scenario: a product linked to two suppliers (e.g. Spiral
Foods as default, Fords Dairy as an alternate) with different SKUs and
pack sizes. A PO raised against the alternate supplier must show that
supplier's own SKU/pack, not the default supplier's.

Covers:
- views/purchase_orders/po_detail.py's "Supplier SKU" / "Supplier Ctn Qty" columns
- views/purchase_orders/add_line_dialog.py's new Supplier SKU field

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from PyQt6.QtWidgets import QApplication

import models.purchase_order as po_model
import models.po_lines as lines_model
import models.product_suppliers as ps_model


@pytest.fixture()
def fords_dairy_id(db_conn):
    db_conn.execute("INSERT INTO suppliers (code, name) VALUES ('FORDS', 'Fords Dairy')")
    db_conn.commit()
    return db_conn.execute("SELECT id FROM suppliers WHERE code='FORDS'").fetchone()["id"]


@pytest.fixture()
def bonsoy_milk(db_conn, dept_id, supplier_id, fords_dairy_id):
    """Bonsoy Milk: default supplier Spiral Foods (12-pack, SPIRAL-123),
    alternate supplier Fords Dairy (6-pack, FORDS-456)."""
    bc = "9300099990001"
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit,
             active, unit, supplier_sku)
        VALUES (?, 'Bonsoy Milk', ?, ?, 5.00, 3.00, 10.0, 12, 'CTN', 1, 'EA', 'SPIRAL-123')
    """, (bc, dept_id, supplier_id))
    db_conn.commit()
    ps_model.save_for_barcode(bc, [
        {"supplier_id": supplier_id, "is_default": True,
         "supplier_sku": "SPIRAL-123", "pack_qty": 12, "pack_unit": "CTN"},
        {"supplier_id": fords_dairy_id, "is_default": False,
         "supplier_sku": "FORDS-456", "pack_qty": 6, "pack_unit": "CTN"},
    ])
    return bc


# ── po_detail.py table columns ────────────────────────────────────────────────

class TestPoDetailSupplierSpecificColumns:
    def test_po_for_alternate_supplier_shows_its_own_sku_and_pack(
        self, qtbot, test_db, bonsoy_milk, fords_dairy_id
    ):
        po_id = po_model.create(fords_dairy_id, '2026-07-01', '', 'admin')
        lines_model.add(po_id, bonsoy_milk, 'Bonsoy Milk', 2, 4.00)

        from views.purchase_orders.po_detail import PODetail
        w = PODetail(po_id, blank=True)
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()

        assert w.table.item(0, 3).text() == "FORDS-456"
        assert w.table.item(0, 2).text() == "6 × CTN"

    def test_po_for_default_supplier_shows_its_own_sku_and_pack(
        self, qtbot, test_db, bonsoy_milk, supplier_id
    ):
        po_id = po_model.create(supplier_id, '2026-07-01', '', 'admin')
        lines_model.add(po_id, bonsoy_milk, 'Bonsoy Milk', 2, 4.00)

        from views.purchase_orders.po_detail import PODetail
        w = PODetail(po_id, blank=True)
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()

        assert w.table.item(0, 3).text() == "SPIRAL-123"
        assert w.table.item(0, 2).text() == "12 × CTN"

    def test_unlinked_product_falls_back_to_product_default(
        self, qtbot, test_db, db_conn, dept_id, supplier_id
    ):
        bc = "9300099990002"
        db_conn.execute("""
            INSERT INTO products
                (barcode, description, department_id, supplier_id,
                 sell_price, cost_price, tax_rate, pack_qty, pack_unit,
                 active, unit, supplier_sku)
            VALUES (?, 'Legacy Product', ?, ?, 5.00, 3.00, 10.0, 3, 'EA', 1, 'EA', 'LEGACY-SKU')
        """, (bc, dept_id, supplier_id))
        db_conn.commit()
        po_id = po_model.create(supplier_id, '2026-07-01', '', 'admin')
        lines_model.add(po_id, bc, 'Legacy Product', 2, 4.00)

        from views.purchase_orders.po_detail import PODetail
        w = PODetail(po_id, blank=True)
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()

        assert w.table.item(0, 3).text() == "LEGACY-SKU"
        assert w.table.item(0, 2).text() == "3 × EA"


# ── add_line_dialog.py Supplier SKU field ────────────────────────────────────────

class TestAddLineDialogSupplierSku:
    def test_shows_alternate_suppliers_sku(
        self, qtbot, test_db, bonsoy_milk, fords_dairy_id
    ):
        po_id = po_model.create(fords_dairy_id, '2026-07-01', '', 'admin')
        from views.purchase_orders.add_line_dialog import AddLineDialog
        dlg = AddLineDialog(po_id, supplier_id=fords_dairy_id)
        qtbot.addWidget(dlg)
        dlg.barcode.setText(bonsoy_milk)
        dlg._on_barcode_enter()

        assert dlg.sku_label.text() == "FORDS-456"
        assert "6" in dlg.pack_label.text()

    def test_shows_default_suppliers_sku(
        self, qtbot, test_db, bonsoy_milk, supplier_id
    ):
        po_id = po_model.create(supplier_id, '2026-07-01', '', 'admin')
        from views.purchase_orders.add_line_dialog import AddLineDialog
        dlg = AddLineDialog(po_id, supplier_id=supplier_id)
        qtbot.addWidget(dlg)
        dlg.barcode.setText(bonsoy_milk)
        dlg._on_barcode_enter()

        assert dlg.sku_label.text() == "SPIRAL-123"
        assert "12" in dlg.pack_label.text()
