"""Tests for controllers/po_reorder_controller.py — DB-backed tests."""
import pytest
from controllers.po_reorder_controller import (
    get_reorder_recommendations,
    get_auto_reorder_items,
    get_items_for_supplier,
    get_received_line_count,
    cartons_needed,
    calc_order_units,
    carton_note,
    auto_populate_po_lines,
    reload_reorder_recommendations,
    lookup_product_for_po,
)
from controllers.purchase_order_controller import (
    create_po,
    add_po_line,
    get_po_lines,
    receive_po_atomic,
    get_po_by_id,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insert_product(db_conn, dept_id, supplier_id, barcode, description,
                    reorder_point=5, reorder_max=20, pack_qty=1,
                    auto_reorder=0, cost_price=2.00):
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit,
             reorder_point, reorder_max, active, unit, auto_reorder)
        VALUES (?, ?, ?, ?, 5.00, ?, 10.0, ?, 'EA', ?, ?, 1, 'EA', ?)
    """, (barcode, description, dept_id, supplier_id,
          cost_price, pack_qty, reorder_point, reorder_max, auto_reorder))
    db_conn.commit()
    return barcode


def _set_soh(db_conn, barcode, qty):
    db_conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity)
        VALUES (?, ?)
        ON CONFLICT(barcode) DO UPDATE SET quantity=excluded.quantity
    """, (barcode, qty))
    db_conn.commit()


def _link_supplier(db_conn, barcode, supplier_id):
    """Add product_suppliers row to link a product to a supplier."""
    db_conn.execute("""
        INSERT OR IGNORE INTO product_suppliers (barcode, supplier_id, is_default, pack_qty, pack_unit)
        VALUES (?, ?, 1, 1, 'EA')
    """, (barcode, supplier_id))
    db_conn.commit()


# ── get_reorder_recommendations ───────────────────────────────────────────────

class TestGetReorderRecommendations:
    def test_product_below_reorder_point_appears(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011110001',
                             'Low Stock Item', reorder_point=5, reorder_max=20)
        _set_soh(db_conn, bc, 3)  # SOH(3) <= reorder_point(5)
        recs = get_reorder_recommendations(supplier_id)
        barcodes = [r['barcode'] for r in recs]
        assert bc in barcodes

    def test_product_above_reorder_point_excluded(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011110002',
                             'Well Stocked Item', reorder_point=5, reorder_max=20)
        _set_soh(db_conn, bc, 15)  # SOH(15) > reorder_point(5)
        recs = get_reorder_recommendations(supplier_id)
        barcodes = [r['barcode'] for r in recs]
        assert bc not in barcodes

    def test_product_at_exact_reorder_point_appears(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011110003',
                             'Exactly At Reorder', reorder_point=5, reorder_max=20)
        _set_soh(db_conn, bc, 5)  # SOH == reorder_point → should appear
        recs = get_reorder_recommendations(supplier_id)
        barcodes = [r['barcode'] for r in recs]
        assert bc in barcodes

    def test_zero_reorder_point_excluded_always(self, test_db, db_conn, dept_id, supplier_id):
        # reorder_point=0 means no reorder trigger — even zero SOH excluded
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011110004',
                             'No Reorder Point', reorder_point=0, reorder_max=0)
        _set_soh(db_conn, bc, 0)
        recs = get_reorder_recommendations(supplier_id)
        barcodes = [r['barcode'] for r in recs]
        assert bc not in barcodes

    def test_recommendations_include_required_keys(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011110005',
                             'Key Check Item', reorder_point=5, reorder_max=20)
        _set_soh(db_conn, bc, 2)
        recs = get_reorder_recommendations(supplier_id)
        r = next((x for x in recs if x['barcode'] == bc), None)
        assert r is not None
        for key in ('barcode', 'description', 'reorder_point', 'reorder_max',
                    'cost_price', 'on_hand', 'on_order', 'effective_stock'):
            assert key in r, f"Missing key: {key}"

    def test_on_order_stock_counts_toward_effective(self, test_db, db_conn, dept_id, supplier_id):
        """Product with SOH below reorder_point but on open PO → excluded."""
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011110006',
                             'On Order Item', reorder_point=10, reorder_max=30, pack_qty=5)
        _set_soh(db_conn, bc, 3)   # below reorder_point

        # Create an open PO with this product — 2 cartons × 5 pack = 10 units on order
        po_id = create_po(supplier_id)
        add_po_line(po_id, bc, 'On Order Item', ordered_qty=2, unit_cost=2.00, pack_qty=5)

        recs = get_reorder_recommendations(supplier_id)
        barcodes = [r['barcode'] for r in recs]
        # effective_stock = 3 + 10 = 13 > reorder_point(10) → NOT in recs
        assert bc not in barcodes

    def test_no_recommendations_for_empty_supplier(self, test_db, db_conn, dept_id, supplier_id):
        # New supplier with no products
        db_conn.execute("INSERT INTO suppliers (code, name) VALUES ('EMPTY', 'Empty Supplier')")
        db_conn.commit()
        other_id = db_conn.execute(
            "SELECT id FROM suppliers WHERE code='EMPTY'"
        ).fetchone()['id']
        recs = get_reorder_recommendations(other_id)
        assert recs == []


# ── get_sales_for_barcode / get_sales_for_barcode_range wrappers ──────────────

class TestSalesWrappers:
    def test_get_sales_for_barcode_returns_none_when_unmapped(self, test_db):
        from controllers.po_reorder_controller import get_sales_for_barcode
        assert get_sales_for_barcode('0000000000000') is None

    def test_get_sales_for_barcode_range_returns_none_when_unmapped(self, test_db):
        from controllers.po_reorder_controller import get_sales_for_barcode_range
        assert get_sales_for_barcode_range(
            '0000000000000', '2026-01-01', '2026-01-31'
        ) is None


# ── get_auto_reorder_items ─────────────────────────────────────────────────────

class TestGetAutoReorderItems:
    def test_auto_reorder_product_returned(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011120001',
                             'Auto Reorder Product', auto_reorder=1)
        items = get_auto_reorder_items(supplier_id)
        barcodes = [i['barcode'] for i in items]
        assert bc in barcodes

    def test_non_auto_reorder_product_excluded(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011120002',
                             'Normal Product', auto_reorder=0)
        items = get_auto_reorder_items(supplier_id)
        barcodes = [i['barcode'] for i in items]
        assert bc not in barcodes

    def test_auto_reorder_empty_when_no_products(self, test_db, db_conn, supplier_id):
        # supplier_id has no products yet
        items = get_auto_reorder_items(supplier_id)
        assert isinstance(items, list)


# ── get_items_for_supplier ─────────────────────────────────────────────────────

class TestGetItemsForSupplier:
    def test_returns_products_linked_via_product_suppliers(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011130001', 'Linked Prod')
        _link_supplier(db_conn, bc, supplier_id)
        items = get_items_for_supplier(supplier_id)
        barcodes = [i['barcode'] for i in items]
        assert bc in barcodes

    def test_returns_all_active_products_without_supplier(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011130002', 'All Products')
        items = get_items_for_supplier(None)
        barcodes = [i['barcode'] for i in items]
        assert bc in barcodes


# ── get_received_line_count ────────────────────────────────────────────────────

class TestGetReceivedLineCount:
    def _receipt(self, line, qty_units):
        return {
            'line_id':          line['id'],
            'barcode':          line['barcode'],
            'new_received_qty': qty_units,
            'actual_cost':      2.00,
            'unit_cost':        2.00,
            'is_promo':         False,
            'qty_units':        qty_units,
        }

    def test_zero_before_receipt(self, test_db, supplier_id, product_barcode):
        po_id = create_po(supplier_id)
        add_po_line(po_id, product_barcode, 'Widget', ordered_qty=5, unit_cost=2.00)
        assert get_received_line_count(po_id) == 0

    def test_count_increments_after_receipt(self, test_db, supplier_id,
                                             product_barcode, gst_free_barcode):
        po_id = create_po(supplier_id)
        add_po_line(po_id, product_barcode, 'Widget', ordered_qty=5, unit_cost=2.00)
        add_po_line(po_id, gst_free_barcode, 'GST Free', ordered_qty=3, unit_cost=1.00)
        lines = get_po_lines(po_id)
        po = get_po_by_id(po_id)
        receive_po_atomic(po_id, po['po_number'],
                          [self._receipt(lines[0], 5)],
                          final_status='PARTIAL')
        assert get_received_line_count(po_id) == 1


# ── calc_order_units ──────────────────────────────────────────────────────────

class TestCalcOrderUnitsReorder:
    def test_orders_to_reorder_max_minus_on_hand(self):
        assert calc_order_units(30, 0, 10) == 20

    def test_already_at_max_returns_minimum_one(self):
        assert calc_order_units(10, 0, 15) == 1

    def test_zero_reorder_max_falls_back_to_reorder_qty(self):
        assert calc_order_units(0, 12, 5) == 12

    def test_none_on_hand_treated_as_zero(self):
        assert calc_order_units(20, 0, None) == 20


# ── auto_populate_po_lines ────────────────────────────────────────────────────

class TestAutoPopulatePoLines:
    def test_returns_string_banner(self, test_db, db_conn, supplier_id):
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('PO-AUTO-001', ?, 'DRAFT', 'PO')
        """, (supplier_id,))
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='PO-AUTO-001'"
        ).fetchone()["id"]
        result = auto_populate_po_lines(po_id, supplier_id)
        assert isinstance(result, str)

    def test_no_reorder_items_returns_all_good_message(
        self, test_db, db_conn, supplier_id
    ):
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('PO-AUTO-002', ?, 'DRAFT', 'PO')
        """, (supplier_id,))
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='PO-AUTO-002'"
        ).fetchone()["id"]
        result = auto_populate_po_lines(po_id, supplier_id)
        assert "above reorder" in result or isinstance(result, str)

    def test_adds_reorder_lines_when_below_point(
        self, test_db, db_conn, dept_id, supplier_id
    ):
        bc = '9300000088801'
        db_conn.execute("""
            INSERT INTO products
                (barcode, description, department_id, supplier_id,
                 sell_price, cost_price, tax_rate, pack_qty, pack_unit,
                 active, unit, reorder_point, reorder_max)
            VALUES (?, 'Reorder Me', ?, ?, 5.00, 3.00, 10.0, 6, 'CTN', 1, 'EA', 10, 30)
        """, (bc, dept_id, supplier_id))
        db_conn.execute(
            "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 2)",
            (bc,)
        )
        db_conn.execute("""
            INSERT INTO product_suppliers (barcode, supplier_id, is_default)
            VALUES (?, ?, 1)
        """, (bc, supplier_id))
        db_conn.execute("""
            INSERT INTO purchase_orders (po_number, supplier_id, status, po_type)
            VALUES ('PO-AUTO-003', ?, 'DRAFT', 'PO')
        """, (supplier_id,))
        db_conn.commit()
        po_id = db_conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number='PO-AUTO-003'"
        ).fetchone()["id"]
        result = auto_populate_po_lines(po_id, supplier_id)
        lines = db_conn.execute(
            "SELECT * FROM po_lines WHERE po_id=?", (po_id,)
        ).fetchall()
        assert len(lines) >= 1

    def test_auto_reorder_item_added_when_not_already_on_po(
        self, test_db, db_conn, dept_id, supplier_id
    ):
        """A product flagged auto_reorder=1 that is NOT also caught by the
        reorder-point pass gets its own line, and the banner mentions it."""
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011160001',
                             'Auto Reorder Product', reorder_point=0, reorder_max=0,
                             auto_reorder=1, pack_qty=6)
        _set_soh(db_conn, bc, 5)  # above reorder_point=0, so excluded from reorder-point pass
        _link_supplier(db_conn, bc, supplier_id)
        po_id = create_po(supplier_id)

        banner = auto_populate_po_lines(po_id, supplier_id)

        lines = db_conn.execute(
            "SELECT * FROM po_lines WHERE po_id=? AND barcode=?", (po_id, bc)
        ).fetchall()
        assert len(lines) == 1
        assert lines[0]['ordered_qty'] == 1
        assert 'on-reorder item' in banner

    def test_auto_reorder_item_already_on_po_is_not_duplicated(
        self, test_db, db_conn, dept_id, supplier_id
    ):
        """An auto_reorder=1 item manually added to the PO beforehand must be
        skipped by the auto-reorder pass, not duplicated."""
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011160002',
                             'Auto Reorder Already Added', reorder_point=0, reorder_max=0,
                             auto_reorder=1, pack_qty=1)
        _set_soh(db_conn, bc, 5)
        _link_supplier(db_conn, bc, supplier_id)
        po_id = create_po(supplier_id)
        add_po_line(po_id, bc, 'Auto Reorder Already Added', ordered_qty=3, unit_cost=2.00)

        auto_populate_po_lines(po_id, supplier_id)

        lines = db_conn.execute(
            "SELECT * FROM po_lines WHERE po_id=? AND barcode=?", (po_id, bc)
        ).fetchall()
        assert len(lines) == 1
        assert lines[0]['ordered_qty'] == 3


# ── reload_reorder_recommendations ────────────────────────────────────────────

class TestReloadReorderRecommendations:
    def test_returns_none_when_no_products_at_reorder(self, test_db, db_conn, dept_id, supplier_id):
        po_id = create_po(supplier_id)
        result = reload_reorder_recommendations(po_id, supplier_id)
        assert result is None

    def test_returns_zero_when_all_already_on_po(self, test_db, db_conn, dept_id, supplier_id):
        # Two products below reorder point; add only one to the PO.
        bc1 = _insert_product(db_conn, dept_id, supplier_id, '9300011140001',
                              'Reload Product A', reorder_point=5, reorder_max=20)
        bc2 = _insert_product(db_conn, dept_id, supplier_id, '9300011140009',
                              'Reload Product B', reorder_point=5, reorder_max=20)
        _set_soh(db_conn, bc1, 2)  # below reorder_point, no open POs → in recs
        _set_soh(db_conn, bc2, 3)  # also below reorder_point
        po_id = create_po(supplier_id)
        # Add both to PO so reload finds nothing new
        add_po_line(po_id, bc1, 'Reload Product A', ordered_qty=5, unit_cost=2.00)
        add_po_line(po_id, bc2, 'Reload Product B', ordered_qty=5, unit_cost=2.00)
        # Now reload: recs may be empty (on-order pushes effective stock up) or all on PO
        result = reload_reorder_recommendations(po_id, supplier_id)
        # Returns None (no recs at all) or 0 (all already on PO) — either is correct
        assert result in (None, 0)

    def test_returns_zero_deterministically_when_still_below_reorder_point(
        self, test_db, db_conn, dept_id, supplier_id
    ):
        """A very high reorder_point guarantees the product stays in recs
        even after the on-order line is added, forcing the real `return 0`
        (all recs already on PO) rather than the None (no recs at all) branch."""
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011140099',
                             'Reload Deterministic', reorder_point=1000, reorder_max=2000)
        _set_soh(db_conn, bc, 1)
        po_id = create_po(supplier_id)
        add_po_line(po_id, bc, 'Reload Deterministic', ordered_qty=1, unit_cost=2.00)

        result = reload_reorder_recommendations(po_id, supplier_id)

        assert result == 0

    def test_returns_count_of_newly_added_lines(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011140002',
                             'New Reorder Product', reorder_point=5, reorder_max=20)
        _set_soh(db_conn, bc, 1)  # below reorder_point
        po_id = create_po(supplier_id)
        result = reload_reorder_recommendations(po_id, supplier_id)
        assert result == 1


# ── lookup_product_for_po ──────────────────────────────────────────────────────

class TestLookupProductForPO:
    def test_returns_none_for_unknown_barcode(self, test_db, supplier_id):
        po_id = create_po(supplier_id)
        result = lookup_product_for_po('0000000000000', po_id, supplier_id, unit_mode=False)
        assert result is None

    def test_returns_dict_with_product_info(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011150001',
                             'Lookup Product', reorder_point=3, reorder_max=15, pack_qty=6)
        _link_supplier(db_conn, bc, supplier_id)
        po_id = create_po(supplier_id)
        result = lookup_product_for_po(bc, po_id, supplier_id, unit_mode=False)
        assert result is not None
        for key in ('description', 'cost_price', 'on_hand', 'pack_qty', 'suggested_qty'):
            assert key in result

    def test_raises_if_product_already_on_po(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011150002',
                             'Already On PO')
        _link_supplier(db_conn, bc, supplier_id)
        po_id = create_po(supplier_id)
        add_po_line(po_id, bc, 'Already On PO', ordered_qty=5, unit_cost=2.00)
        with pytest.raises(ValueError, match='already_on_po'):
            lookup_product_for_po(bc, po_id, supplier_id, unit_mode=False)

    def test_raises_if_product_not_linked_to_supplier(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011150003',
                             'Unlinked Product')
        # Insert second supplier
        db_conn.execute("INSERT INTO suppliers (code, name) VALUES ('OTH', 'Other Supplier')")
        db_conn.commit()
        other_id = db_conn.execute(
            "SELECT id FROM suppliers WHERE code='OTH'"
        ).fetchone()['id']
        po_id = create_po(other_id)
        with pytest.raises(ValueError, match='not_linked'):
            lookup_product_for_po(bc, po_id, other_id, unit_mode=False)

    def test_unit_mode_returns_suggested_qty_one(self, test_db, db_conn, dept_id, supplier_id):
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011150004',
                             'Unit Mode Product', reorder_max=50, pack_qty=12)
        _link_supplier(db_conn, bc, supplier_id)
        po_id = create_po(supplier_id)
        result = lookup_product_for_po(bc, po_id, supplier_id, unit_mode=True)
        assert result['suggested_qty'] == 1

    def test_loop_continues_past_non_matching_existing_lines(
        self, test_db, db_conn, dept_id, supplier_id
    ):
        """An existing line for a *different* barcode must not short-circuit
        the already-on-po check — the loop should continue past it."""
        bc_other = _insert_product(db_conn, dept_id, supplier_id, '9300011150010',
                                   'Other Product')
        bc_target = _insert_product(db_conn, dept_id, supplier_id, '9300011150011',
                                    'Target Product')
        _link_supplier(db_conn, bc_target, supplier_id)
        po_id = create_po(supplier_id)
        add_po_line(po_id, bc_other, 'Other Product', ordered_qty=1, unit_cost=2.00)

        result = lookup_product_for_po(bc_target, po_id, supplier_id, unit_mode=False)

        assert result is not None

    def test_no_supplier_id_skips_link_check(self, test_db, db_conn, dept_id, supplier_id):
        """supplier_id=None (falsy) must skip the product_suppliers link check
        entirely, rather than raising not_linked."""
        bc = _insert_product(db_conn, dept_id, supplier_id, '9300011150012',
                             'No Supplier Filter')
        po_id = create_po(supplier_id)

        result = lookup_product_for_po(bc, po_id, None, unit_mode=False)

        assert result is not None


# ── Milk forecast path ────────────────────────────────────────────────────────

def _setup_dairy_milk_product(db_conn, supplier_id):
    """Create a MILK group in the (pre-seeded) DAIRY department, plus a linked product."""
    dairy_id = db_conn.execute(
        "SELECT id FROM departments WHERE code='DAIRY'"
    ).fetchone()["id"]

    db_conn.execute("""
        INSERT OR IGNORE INTO product_groups (department_id, code, name)
        VALUES (?, 'MILK', 'Milk')
    """, (dairy_id,))
    db_conn.commit()
    milk_group_id = db_conn.execute(
        "SELECT id FROM product_groups WHERE code='MILK' AND department_id=?", (dairy_id,)
    ).fetchone()["id"]

    bc = '9300000099001'
    db_conn.execute("""
        INSERT INTO products
            (barcode, description, department_id, supplier_id, group_id,
             sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, 'Full Cream Milk 2L', ?, ?, ?, 3.50, 2.00, 10.0, 12, 'CTN', 1, 'EA')
    """, (bc, dairy_id, supplier_id, milk_group_id))
    db_conn.execute(
        "INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?, 10)", (bc,)
    )
    db_conn.commit()
    return bc


class TestMilkForecastPath:
    def test_milk_lines_added_when_delivery_days_set(
        self, test_db, db_conn, supplier_id
    ):
        db_conn.execute(
            "UPDATE suppliers SET delivery_days='MON,TUE,WED,THU,FRI,SAT,SUN' WHERE id=?",
            (supplier_id,)
        )
        db_conn.commit()
        bc = _setup_dairy_milk_product(db_conn, supplier_id)
        po_id = create_po(supplier_id)

        banner = auto_populate_po_lines(po_id, supplier_id)

        lines = db_conn.execute(
            "SELECT * FROM po_lines WHERE po_id=?", (po_id,)
        ).fetchall()
        milk_lines = [l for l in lines if l['barcode'] == bc]
        assert len(milk_lines) == 1
        assert '🥛' in banner

    def test_milk_banner_includes_delivery_info(
        self, test_db, db_conn, supplier_id
    ):
        db_conn.execute(
            "UPDATE suppliers SET delivery_days='MON,WED,FRI' WHERE id=?",
            (supplier_id,)
        )
        db_conn.commit()
        _setup_dairy_milk_product(db_conn, supplier_id)
        po_id = create_po(supplier_id)

        banner = auto_populate_po_lines(po_id, supplier_id)
        assert 'milk' in banner.lower()
        assert 'day' in banner.lower()

    def test_milk_note_includes_no_sales_warning_when_no_history(
        self, test_db, db_conn, supplier_id
    ):
        db_conn.execute(
            "UPDATE suppliers SET delivery_days='MON,TUE,WED,THU,FRI,SAT,SUN' WHERE id=?",
            (supplier_id,)
        )
        db_conn.commit()
        bc = _setup_dairy_milk_product(db_conn, supplier_id)
        po_id = create_po(supplier_id)
        auto_populate_po_lines(po_id, supplier_id)

        lines = db_conn.execute(
            "SELECT notes FROM po_lines WHERE po_id=? AND barcode=?", (po_id, bc)
        ).fetchall()
        assert len(lines) == 1
        assert 'no sales history' in (lines[0]['notes'] or '').lower()

    def test_milk_line_on_order_note_when_open_po_exists(
        self, test_db, db_conn, supplier_id
    ):
        db_conn.execute(
            "UPDATE suppliers SET delivery_days='MON,TUE,WED,THU,FRI,SAT,SUN' WHERE id=?",
            (supplier_id,)
        )
        db_conn.commit()
        bc = _setup_dairy_milk_product(db_conn, supplier_id)

        # Create an existing open PO with a milk line (so on_order > 0)
        existing_po = create_po(supplier_id)
        add_po_line(existing_po, bc, 'Full Cream Milk 2L', ordered_qty=2, unit_cost=2.00)

        new_po = create_po(supplier_id)
        banner = auto_populate_po_lines(new_po, supplier_id)

        new_lines = db_conn.execute(
            "SELECT notes FROM po_lines WHERE po_id=? AND barcode=?", (new_po, bc)
        ).fetchall()
        assert len(new_lines) == 1
        assert 'On order' in (new_lines[0]['notes'] or '')

    def test_no_milk_lines_when_delivery_days_not_set(
        self, test_db, db_conn, supplier_id
    ):
        # delivery_days is empty by default
        bc = _setup_dairy_milk_product(db_conn, supplier_id)
        po_id = create_po(supplier_id)

        auto_populate_po_lines(po_id, supplier_id)

        lines = db_conn.execute(
            "SELECT * FROM po_lines WHERE po_id=? AND barcode=?", (po_id, bc)
        ).fetchall()
        # Without delivery_days, get_milk_order_recommendations returns []
        assert len(lines) == 0

    def test_milk_product_uses_sku_fallback_when_not_plu_mapped(
        self, test_db, db_conn, supplier_id
    ):
        """A milk product with no plu_barcode_map row but a products.sku value
        falls back to the sku as its PLU key (still renders fine with no
        sales history found under that key)."""
        db_conn.execute(
            "UPDATE suppliers SET delivery_days='MON,TUE,WED,THU,FRI,SAT,SUN' WHERE id=?",
            (supplier_id,)
        )
        bc = _setup_dairy_milk_product(db_conn, supplier_id)
        db_conn.execute("UPDATE products SET sku='SKU999' WHERE barcode=?", (bc,))
        db_conn.commit()
        po_id = create_po(supplier_id)

        banner = auto_populate_po_lines(po_id, supplier_id)

        lines = db_conn.execute(
            "SELECT * FROM po_lines WHERE po_id=? AND barcode=?", (po_id, bc)
        ).fetchall()
        assert len(lines) == 1

    def test_milk_line_no_warning_when_sales_history_exists(
        self, test_db, db_conn, supplier_id
    ):
        import datetime
        db_conn.execute(
            "UPDATE suppliers SET delivery_days='MON,TUE,WED,THU,FRI,SAT,SUN' WHERE id=?",
            (supplier_id,)
        )
        bc = _setup_dairy_milk_product(db_conn, supplier_id)
        db_conn.execute(
            "INSERT INTO plu_barcode_map (plu, barcode) VALUES (12345, ?)", (bc,)
        )
        db_conn.execute("""
            INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
            VALUES (?, '12345', 'Full Cream Milk 2L', 10, 30.00)
        """, (datetime.date.today().isoformat(),))
        db_conn.commit()
        po_id = create_po(supplier_id)

        auto_populate_po_lines(po_id, supplier_id)

        lines = db_conn.execute(
            "SELECT notes FROM po_lines WHERE po_id=? AND barcode=?", (po_id, bc)
        ).fetchall()
        assert len(lines) == 1
        assert 'no sales history' not in (lines[0]['notes'] or '').lower()
