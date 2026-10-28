"""po_lines.received_units — exact units received, independent of carton rounding.

Regression: receiving 1 unit of a 6-pack was recorded as 1 carton, so PO history,
GST reports, outstanding quantities and PO reversal all treated it as 6 units.
"""
import sqlite3

import pytest

import config.constants as constants
import controllers.purchase_order_controller as po_ctrl
import database.migrations as mig
import models.po_lines as lines_model
import models.purchase_order as po_model
from database.connection import get_connection
from database.schema import SCHEMA
from views.purchase_orders.po_history_data import compute_po_history_data


@pytest.fixture()
def partial_po(test_db, supplier_id, product_barcode):
    """SENT PO: 1 carton of 6 ordered, 1 unit received (PO-01403 scenario)."""
    po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
    lines_model.add(po_id, product_barcode, "Test Product", 1, 7.10, "", 6)
    po_model.update_status(po_id, constants.PO_STATUS_SENT)
    line = lines_model.get_by_po(po_id)[0]
    po = po_model.get_by_id(po_id)
    po_ctrl.receive_po_atomic(po_id, po["po_number"], [{
        "line_id": line["id"], "barcode": product_barcode,
        "new_received_qty": 1, "actual_cost": 7.10, "unit_cost": 7.10,
        "is_promo": False, "qty_units": 1,
    }], constants.PO_STATUS_PARTIAL)
    return po_id


class TestPartialCartonReceive:
    def test_receive_atomic_records_exact_units(self, partial_po):
        line = lines_model.get_by_po(partial_po)[0]
        assert line["received_units"] == 1
        assert line["received_qty"] == 1

    def test_second_receive_accumulates_units(self, partial_po, product_barcode):
        line = lines_model.get_by_po(partial_po)[0]
        po = po_model.get_by_id(partial_po)
        po_ctrl.receive_po_atomic(partial_po, po["po_number"], [{
            "line_id": line["id"], "barcode": product_barcode,
            "new_received_qty": 1, "actual_cost": None, "unit_cost": None,
            "is_promo": False, "qty_units": 5,
        }], constants.PO_STATUS_RECEIVED)
        assert lines_model.get_by_po(partial_po)[0]["received_units"] == 6

    def test_history_values_received_units_not_full_carton(self, partial_po):
        data = compute_po_history_data(partial_po)
        ld = data.lines[0]
        assert ld.recv_units == 1
        assert ld.line_ex == pytest.approx(7.10)
        assert data.grand_ex == pytest.approx(7.10)

    def test_reverse_removes_only_units_received(self, partial_po, product_barcode):
        conn = get_connection()
        before = conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()[0]
        po_model.reverse(partial_po, "admin")
        after = conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()[0]
        conn.close()
        assert before - after == 1

    def test_outstanding_and_unreceived_use_units(self, partial_po, product_barcode):
        assert lines_model.get_on_order_total(product_barcode) == 5
        unreceived = lines_model.get_unreceived(partial_po)
        assert len(unreceived) == 1
        assert unreceived[0]["ordered_units"] == 6
        assert unreceived[0]["received_units"] == 1


class TestReceiveHelpers:
    def test_correct_received_recomputes_units(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        lines_model.add(po_id, product_barcode, "Test Product", 4, 2.00, "", 6)
        line_id = lines_model.get_by_po(po_id)[0]["id"]
        lines_model.correct_received(line_id, 3)
        assert lines_model.get_by_po(po_id)[0]["received_units"] == 18

    def test_unit_mode_po_does_not_multiply_by_pack(self, test_db, supplier_id, product_barcode):
        po_id = po_model.create(supplier_id, "2026-06-01", "", "admin")
        conn = get_connection()
        conn.execute("UPDATE purchase_orders SET po_type='IO' WHERE id=?", (po_id,))
        conn.commit()
        conn.close()
        lines_model.add(po_id, product_barcode, "Test Product", 10, 2.00, "", 12)
        line_id = lines_model.get_by_po(po_id)[0]["id"]
        lines_model.receive(line_id, 4)
        assert lines_model.get_by_po(po_id)[0]["received_units"] == 4


class TestMigrateV76:
    def _db(self, tmp_path):
        c = sqlite3.connect(str(tmp_path / "v76.db"))
        c.row_factory = sqlite3.Row
        c.executescript(SCHEMA)
        c.execute("INSERT INTO suppliers (code, name) VALUES ('S', 'Sup')")
        c.execute("INSERT INTO products (barcode, description, department_id) VALUES ('B1','B1',1)")
        c.execute("INSERT INTO products (barcode, description, department_id) VALUES ('B2','B2',1)")
        return c

    def _po(self, c, number, po_type="PO"):
        c.execute("INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)"
                  " VALUES (?, 1, 'RECEIVED', ?)", (number, po_type))
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _line(self, c, po_id, barcode, ordered, received, pack):
        c.execute("INSERT INTO po_lines (po_id, barcode, description, ordered_qty,"
                  " received_qty, pack_qty) VALUES (?, ?, 'd', ?, ?, ?)",
                  (po_id, barcode, ordered, received, pack))

    def _move(self, c, barcode, qty, ref, mtype="RECEIPT"):
        c.execute("INSERT INTO stock_movements (barcode, movement_type, quantity, reference)"
                  " VALUES (?, ?, ?, ?)", (barcode, mtype, qty, ref))

    def _units(self, c, barcode):
        return c.execute("SELECT received_units FROM po_lines WHERE barcode=?",
                         (barcode,)).fetchone()[0]

    def test_partial_receive_recovered_from_movements(self, tmp_path):
        c = self._db(tmp_path)
        po = self._po(c, "PO-1")
        self._line(c, po, "B1", 1, 1, 6)
        self._move(c, "B1", 1, "PO-1")
        mig.migrate_v76(c)
        assert self._units(c, "B1") == 1

    def test_full_cartons_match_movements(self, tmp_path):
        c = self._db(tmp_path)
        po = self._po(c, "PO-2")
        self._line(c, po, "B1", 2, 2, 6)
        self._move(c, "B1", 12, "PO-2")
        mig.migrate_v76(c)
        assert self._units(c, "B1") == 12

    def test_inconsistent_movements_fall_back_to_cartons_times_pack(self, tmp_path):
        c = self._db(tmp_path)
        po = self._po(c, "PO-3")
        self._line(c, po, "B1", 2, 2, 6)
        self._move(c, "B1", 60, "PO-3")   # nowhere near 2 cartons
        mig.migrate_v76(c)
        assert self._units(c, "B1") == 12

    def test_duplicate_barcode_lines_use_fallback(self, tmp_path):
        c = self._db(tmp_path)
        po = self._po(c, "PO-4")
        self._line(c, po, "B1", 1, 1, 6)
        self._line(c, po, "B1", 1, 1, 6)
        self._move(c, "B1", 7, "PO-4")
        mig.migrate_v76(c)
        rows = c.execute("SELECT received_units FROM po_lines ORDER BY id").fetchall()
        assert [r[0] for r in rows] == [6, 6]

    def test_unit_mode_po_uses_received_qty_directly(self, tmp_path):
        c = self._db(tmp_path)
        po = self._po(c, "IO-1", "IO")
        self._line(c, po, "B2", 10, 4, 12)
        mig.migrate_v76(c)
        assert self._units(c, "B2") == 4

    def test_is_idempotent(self, tmp_path):
        c = self._db(tmp_path)
        po = self._po(c, "PO-5")
        self._line(c, po, "B1", 1, 1, 6)
        self._move(c, "B1", 1, "PO-5")
        mig.migrate_v76(c)
        mig.migrate_v76(c)
        assert self._units(c, "B1") == 1


class TestReverseReopensPo:
    def test_reversal_returns_po_to_sent_and_clears_receipt(
        self, partial_po, product_barcode
    ):
        conn = get_connection()
        conn.execute("UPDATE purchase_orders SET supplier_invoice_number='INV-9', "
                     "received_at=CURRENT_TIMESTAMP WHERE id=?", (partial_po,))
        conn.execute("INSERT INTO po_charges (po_id, description, tax_rate, amount_inc_tax) "
                     "VALUES (?, 'Freight', 10, 11)", (partial_po,))
        conn.commit()
        conn.close()

        po_model.reverse(partial_po, "admin")

        po = po_model.get_by_id(partial_po)
        line = lines_model.get_by_po(partial_po)[0]
        conn = get_connection()
        charges = conn.execute("SELECT COUNT(*) FROM po_charges WHERE po_id=?",
                               (partial_po,)).fetchone()[0]
        conn.close()
        assert po["status"] == "SENT"
        assert po["supplier_invoice_number"] == ""
        assert po["received_at"] is None
        assert (line["received_qty"], line["received_units"]) == (0, 0)
        assert charges == 0

    def test_reopened_po_can_be_received_again(self, partial_po, product_barcode):
        po_model.reverse(partial_po, "admin")
        line = lines_model.get_by_po(partial_po)[0]
        po = po_model.get_by_id(partial_po)
        po_ctrl.receive_po_atomic(partial_po, po["po_number"], [{
            "line_id": line["id"], "barcode": product_barcode,
            "new_received_qty": 1, "actual_cost": None, "unit_cost": None,
            "is_promo": False, "qty_units": 6,
        }], constants.PO_STATUS_RECEIVED)
        assert lines_model.get_by_po(partial_po)[0]["received_units"] == 6
        assert lines_model.get_on_order_total(product_barcode) == 0

    def test_reopened_po_counts_as_on_order_and_is_cancellable(
        self, partial_po, product_barcode
    ):
        po_model.reverse(partial_po, "admin")
        assert lines_model.get_on_order_total(product_barcode) == 6
        po_model.cancel(partial_po)
        assert po_model.get_by_id(partial_po)["status"] == "CANCELLED"

    def test_not_supplied_note_cleared_on_reopen(self, partial_po):
        line_id = lines_model.get_by_po(partial_po)[0]["id"]
        conn = get_connection()
        conn.execute("UPDATE po_lines SET notes='NOT SUPPLIED: out of stock' WHERE id=?",
                     (line_id,))
        conn.commit()
        conn.close()
        po_model.reverse(partial_po, "admin")
        assert lines_model.get_by_po(partial_po)[0]["notes"] is None
