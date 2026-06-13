"""Tests for the per-department negative-SOH clamp (departments.no_negative_soh).

Departments like Fresh have drifting counts, so a negative SOH is noise: any
movement that would take a product below zero clamps the stored SOH to zero
and records a compensating ADJUSTMENT_IN movement so movement-based reports
still reconcile with the stored quantity.
"""
import pytest

import models.stock_on_hand as soh_model


@pytest.fixture()
def fresh_dept_id(db_conn):
    """The FRESH department with no_negative_soh enabled.

    The schema cannot seed the flag (it must execute against pre-v55 DBs),
    so production gets it from migrate_v55; test DBs are schema-only and
    enable it here. TestFreshDefault covers the migration path itself.
    """
    db_conn.execute("UPDATE departments SET no_negative_soh=1 WHERE code='FRESH'")
    db_conn.commit()
    row = db_conn.execute("SELECT id FROM departments WHERE code='FRESH'").fetchone()
    return row["id"]


@pytest.fixture()
def fresh_barcode(db_conn, fresh_dept_id, supplier_id):
    """A product in the Fresh department."""
    bc = "9300000000077"
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, 'Fresh Apples', ?, ?, 4.50, 2.00, 0.0, 1, 'KG', 1, 'KG')
    """, (bc, fresh_dept_id, supplier_id))
    db_conn.commit()
    return bc


def _soh(barcode):
    rec = soh_model.get_by_barcode(barcode)
    return rec["quantity"] if rec else None


def _movements(db_conn, barcode):
    return db_conn.execute(
        "SELECT movement_type, quantity, notes FROM stock_movements"
        " WHERE barcode=? ORDER BY id",
        (barcode,)
    ).fetchall()


class TestFreshDefault:
    def test_migration_enables_flag_for_fresh_only(self, test_db, db_conn):
        import database.migrations as mig
        mig.migrate_v55(db_conn)
        rows = db_conn.execute(
            "SELECT code FROM departments WHERE no_negative_soh = 1"
        ).fetchall()
        assert [r["code"] for r in rows] == ["FRESH"]

    def test_db_meta_seeded_with_single_row(self, db_conn):
        assert db_conn.execute("SELECT COUNT(*) FROM db_meta").fetchone()[0] == 1

    def test_db_meta_seeded_below_v55_so_migration_runs(self, db_conn):
        # The schema cannot set the FRESH default itself (it runs against
        # pre-v55 DBs), so fresh installs must replay migrate_v55 once.
        assert db_conn.execute("SELECT version FROM db_meta").fetchone()[0] == 54


class TestAdjustClamp:
    def test_fresh_product_clamps_at_zero(self, test_db, db_conn, fresh_barcode):
        soh_model.adjust(fresh_barcode, 2, "RECEIPT", "PO-001", "", "admin")
        soh_model.adjust(fresh_barcode, -5, "WASTAGE", "", "", "admin")
        assert _soh(fresh_barcode) == 0

    def test_clamp_records_compensating_movement(self, test_db, db_conn, fresh_barcode):
        soh_model.adjust(fresh_barcode, 2, "RECEIPT", "PO-001", "", "admin")
        soh_model.adjust(fresh_barcode, -5, "WASTAGE", "", "", "admin")
        moves = _movements(db_conn, fresh_barcode)
        # RECEIPT +2, WASTAGE -5, then ADJUSTMENT_IN +3 to clamp back to zero
        assert [(m["movement_type"], m["quantity"]) for m in moves] == [
            ("RECEIPT", 2), ("WASTAGE", -5), ("ADJUSTMENT_IN", 3),
        ]
        assert "Auto-clamp" in moves[-1]["notes"]

    def test_non_fresh_product_can_go_negative(self, test_db, db_conn, product_barcode):
        soh_model.adjust(product_barcode, 2, "RECEIPT", "PO-001", "", "admin")
        soh_model.adjust(product_barcode, -5, "WASTAGE", "", "", "admin")
        assert _soh(product_barcode) == -3
        # No compensating movement for unflagged departments
        moves = _movements(db_conn, product_barcode)
        assert [m["movement_type"] for m in moves] == ["RECEIPT", "WASTAGE"]

    def test_no_clamp_when_result_is_positive(self, test_db, db_conn, fresh_barcode):
        soh_model.adjust(fresh_barcode, 10, "RECEIPT", "PO-001", "", "admin")
        soh_model.adjust(fresh_barcode, -4, "SALE", "", "", "admin")
        assert _soh(fresh_barcode) == 6
        moves = _movements(db_conn, fresh_barcode)
        assert [m["movement_type"] for m in moves] == ["RECEIPT", "SALE"]

    def test_flag_can_be_disabled(self, test_db, db_conn, fresh_barcode):
        db_conn.execute("UPDATE departments SET no_negative_soh=0 WHERE code='FRESH'")
        db_conn.commit()
        soh_model.adjust(fresh_barcode, -5, "WASTAGE", "", "", "admin")
        assert _soh(fresh_barcode) == -5


class TestPosSaleClamp:
    def test_pos_sale_clamps_fresh_product(self, test_db, db_conn, fresh_barcode):
        soh_model.adjust(fresh_barcode, 1, "RECEIPT", "PO-001", "", "admin")
        result = soh_model.record_pos_sale_atomic(
            "POS-CLAMP-1", "2026-06-12", "op",
            [{"barcode": fresh_barcode, "qty": 4, "line_total": 18.0, "description": "Apples"}],
        )
        assert result is True
        assert _soh(fresh_barcode) == 0
        moves = _movements(db_conn, fresh_barcode)
        assert ("ADJUSTMENT_IN", 3) in [(m["movement_type"], m["quantity"]) for m in moves]

    def test_pos_sale_non_fresh_goes_negative(self, test_db, product_barcode):
        soh_model.record_pos_sale_atomic(
            "POS-CLAMP-2", "2026-06-12", "op",
            [{"barcode": product_barcode, "qty": 3, "line_total": 10.5, "description": ""}],
        )
        assert _soh(product_barcode) == -3


class TestMigrationBackfill:
    def test_existing_negative_fresh_soh_zeroed(self, test_db, db_conn, fresh_barcode):
        """migrate_v55 zeroes pre-existing negative SOH in flagged departments."""
        import database.migrations as mig
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, -12)",
            (fresh_barcode,))
        db_conn.commit()

        mig.migrate_v55(db_conn)

        assert _soh(fresh_barcode) == 0
        moves = _movements(db_conn, fresh_barcode)
        assert [(m["movement_type"], m["quantity"]) for m in moves] == [
            ("ADJUSTMENT_IN", 12),
        ]

    def test_negative_soh_outside_flagged_departments_untouched(
            self, test_db, db_conn, product_barcode):
        import database.migrations as mig
        db_conn.execute(
            "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, -7)",
            (product_barcode,))
        db_conn.commit()

        mig.migrate_v55(db_conn)

        assert _soh(product_barcode) == -7


class TestDepartmentModel:
    def test_update_persists_flag(self, test_db, db_conn):
        import models.department as dept_model
        row = db_conn.execute("SELECT * FROM departments WHERE code='GROC'").fetchone()
        dept_model.update(row["id"], row["code"], row["name"], 1, no_negative_soh=1)
        after = db_conn.execute(
            "SELECT no_negative_soh FROM departments WHERE code='GROC'"
        ).fetchone()
        assert after["no_negative_soh"] == 1

    def test_create_with_flag(self, test_db, db_conn):
        import models.department as dept_model
        dept_model.create("FLWR", "Flowers", no_negative_soh=1)
        row = db_conn.execute(
            "SELECT no_negative_soh FROM departments WHERE code='FLWR'"
        ).fetchone()
        assert row["no_negative_soh"] == 1
