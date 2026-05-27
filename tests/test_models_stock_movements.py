"""Tests for models/stock_movements.py."""
import models.stock_movements as movements_model
import models.stock_on_hand as soh_model


class TestGetByBarcode:
    def test_empty_for_product_with_no_movements(self, test_db, product_barcode):
        assert list(movements_model.get_by_barcode(product_barcode)) == []

    def test_returns_movement_after_adjust(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 10, 'ADJUSTMENT', reference='REF1')
        rows = movements_model.get_by_barcode(product_barcode)
        assert len(rows) == 1
        assert rows[0]['movement_type'] == 'ADJUSTMENT'
        assert rows[0]['quantity'] == 10

    def test_newest_first_ordering(self, test_db, db_conn, product_barcode):
        # Insert with explicit timestamps to guarantee ordering regardless of test speed
        db_conn.execute("""
            INSERT INTO stock_movements (barcode, movement_type, quantity, reference, created_at)
            VALUES (?, 'ADJUSTMENT', 5, 'FIRST', '2026-01-01 10:00:00')
        """, (product_barcode,))
        db_conn.execute("""
            INSERT INTO stock_movements (barcode, movement_type, quantity, reference, created_at)
            VALUES (?, 'ADJUSTMENT', 3, 'SECOND', '2026-01-01 11:00:00')
        """, (product_barcode,))
        db_conn.commit()
        rows = movements_model.get_by_barcode(product_barcode)
        assert rows[0]['reference'] == 'SECOND'

    def test_filter_by_move_type(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 10, 'RECEIPT', reference='R1')
        soh_model.adjust(product_barcode, -2, 'SALE', reference='S1')
        receipts = movements_model.get_by_barcode(product_barcode, move_type='RECEIPT')
        assert all(r['movement_type'] == 'RECEIPT' for r in receipts)
        assert len(receipts) == 1

    def test_move_type_all_returns_everything(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 10, 'RECEIPT')
        soh_model.adjust(product_barcode, -1, 'SALE')
        rows = movements_model.get_by_barcode(product_barcode, move_type='ALL')
        assert len(rows) == 2

    def test_reference_stored(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 1, 'ADJUSTMENT', reference='MYREF')
        row = movements_model.get_by_barcode(product_barcode)[0]
        assert row['reference'] == 'MYREF'


class TestGetRecentAdjustments:
    def test_empty_when_no_adjustments(self, test_db, product_barcode):
        assert movements_model.get_recent_adjustments() == []

    def test_excludes_sales_and_receipts(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 5, 'SALE')
        soh_model.adjust(product_barcode, 10, 'RECEIPT')
        assert movements_model.get_recent_adjustments() == []

    def test_includes_adjustment_type(self, test_db, product_barcode):
        soh_model.adjust(product_barcode, 3, 'ADJUSTMENT', reference='ADJ1')
        rows = movements_model.get_recent_adjustments()
        assert len(rows) == 1
        # tuple: (created_at, barcode, description, movement_type, quantity, reference, notes)
        assert rows[0][1] == product_barcode
        assert rows[0][3] == 'ADJUSTMENT'

    def test_respects_limit(self, test_db, product_barcode):
        for i in range(5):
            soh_model.adjust(product_barcode, i + 1, 'ADJUSTMENT', reference=f'ADJ{i}')
        rows = movements_model.get_recent_adjustments(limit=3)
        assert len(rows) == 3
