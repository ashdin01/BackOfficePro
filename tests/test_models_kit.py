"""Tests for models/kit.py — recipes and assembly (Xmas hampers)."""
import pytest
import models.kit as kit_model


def _product(conn, dept_id, barcode, desc, cost, soh=0.0):
    conn.execute("""
        INSERT INTO products (barcode, description, department_id, sell_price,
                              cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, ?, ?, 10, ?, 10.0, 1, 'EA', 1, 'EA')
    """, (barcode, desc, dept_id, cost))
    conn.execute("INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, ?)", (barcode, soh))
    conn.commit()
    return barcode


@pytest.fixture()
def hamper(db_conn, dept_id):
    """A LARGE hamper (cost 0) of 1 brandy + 2 dry cider + 1 gummies, comps well stocked."""
    parent = _product(db_conn, dept_id, "H1", "Harcourt Xmas Hamper LARGE", 0.0)
    brandy = _product(db_conn, dept_id, "C1", "Brandy 200ml", 20.0, soh=10)
    dry    = _product(db_conn, dept_id, "C2", "Dry Cider 500ml", 3.0, soh=30)
    gum    = _product(db_conn, dept_id, "C3", "Gummies 250g", 4.5, soh=10)
    kit_model.add_component(parent, brandy, 1)
    kit_model.add_component(parent, dry, 2)
    kit_model.add_component(parent, gum, 1)
    return parent


def _soh(conn, barcode):
    return conn.execute("SELECT quantity FROM stock_on_hand WHERE barcode=?", (barcode,)).fetchone()[0]


class TestRecipe:
    def test_components_listed_with_cost_and_stock(self, hamper):
        comps = {c['barcode']: c for c in kit_model.get_components(hamper)}
        assert comps['C2']['qty'] == 2 and comps['C2']['soh'] == 30
        assert comps['C1']['cost_price'] == pytest.approx(20.0)

    def test_recipe_cost_sums_cost_times_qty(self, hamper):
        assert kit_model.get_recipe_cost(hamper) == pytest.approx(20 + 2 * 3 + 4.5)

    def test_max_buildable_limited_by_scarcest_component(self, hamper, db_conn):
        assert kit_model.get_max_buildable(hamper) == 10      # brandy/gummies 10, dry 30/2=15
        db_conn.execute("UPDATE stock_on_hand SET quantity=5 WHERE barcode='C2'")
        db_conn.commit()
        assert kit_model.get_max_buildable(hamper) == 2

    def test_get_kits_lists_parent_once(self, hamper):
        kits = kit_model.get_kits()
        assert [k['barcode'] for k in kits] == [hamper]
        assert kits[0]['component_count'] == 3

    def test_add_rejects_self_duplicate_and_bad_qty(self, hamper):
        with pytest.raises(ValueError):
            kit_model.add_component(hamper, hamper, 1)
        with pytest.raises(ValueError, match="already"):
            kit_model.add_component(hamper, "C1", 1)
        with pytest.raises(ValueError):
            kit_model.add_component(hamper, "C1", 0)

    def test_add_rejects_nesting_both_ways(self, hamper, db_conn, dept_id):
        _product(db_conn, dept_id, "H2", "Hamper MEDIUM", 0)
        with pytest.raises(ValueError, match="nested"):
            kit_model.add_component("H2", hamper, 1)     # kit inside a kit
        with pytest.raises(ValueError, match="nested"):
            kit_model.add_component("C1", "H1", 1)       # parent of another kit as a component

    def test_update_and_delete_component(self, hamper):
        comp = next(c for c in kit_model.get_components(hamper) if c['barcode'] == 'C2')
        kit_model.update_component_qty(comp['id'], 3)
        assert next(c for c in kit_model.get_components(hamper) if c['barcode'] == 'C2')['qty'] == 3
        kit_model.delete_component(comp['id'])
        assert 'C2' not in [c['barcode'] for c in kit_model.get_components(hamper)]


class TestBuild:
    def test_build_moves_stock_both_ways(self, hamper, db_conn):
        kit_model.build(hamper, 4)
        assert _soh(db_conn, hamper) == 4
        assert _soh(db_conn, "C1") == 6      # 10 - 4
        assert _soh(db_conn, "C2") == 22     # 30 - 8
        assert _soh(db_conn, "C3") == 6

    def test_build_writes_linked_movements(self, hamper, db_conn):
        build_id = kit_model.build(hamper, 2)
        rows = db_conn.execute(
            "SELECT barcode, movement_type, quantity FROM stock_movements WHERE reference=?",
            (f"ASM-{build_id}",)).fetchall()
        by = {(r['barcode'], r['movement_type']): r['quantity'] for r in rows}
        assert by[(hamper, 'ASSEMBLY_IN')] == 2
        assert by[('C1', 'ASSEMBLY_OUT')] == -2
        assert by[('C2', 'ASSEMBLY_OUT')] == -4

    def test_build_sets_parent_cost_to_recipe_cost(self, hamper, db_conn):
        kit_model.build(hamper, 1)
        cost = db_conn.execute("SELECT cost_price FROM products WHERE barcode=?", (hamper,)).fetchone()[0]
        assert cost == pytest.approx(30.5)

    def test_cost_change_revalues_kits_already_on_hand(self, hamper, db_conn):
        kit_model.build(hamper, 2)                       # cost 0 -> 30.5, none on hand yet
        db_conn.execute("UPDATE products SET cost_price=22 WHERE barcode='C1'")   # recipe now 32.5
        db_conn.commit()
        kit_model.build(hamper, 1)
        rv = db_conn.execute(
            "SELECT old_cost, new_cost, value_delta FROM stock_movements"
            " WHERE barcode=? AND movement_type='REVALUE'", (hamper,)).fetchall()
        assert len(rv) == 1
        assert rv[0]['old_cost'] == pytest.approx(30.5)
        assert rv[0]['new_cost'] == pytest.approx(32.5)
        assert rv[0]['value_delta'] == pytest.approx(2.0 * 2)   # 2 kits on hand at the time

    def test_build_allowed_when_component_short_or_negative(self, hamper, db_conn):
        db_conn.execute("UPDATE stock_on_hand SET quantity=-2 WHERE barcode='C3'")
        db_conn.execute("UPDATE stock_on_hand SET quantity=1 WHERE barcode='C1'")
        db_conn.commit()
        kit_model.build(hamper, 5)
        assert _soh(db_conn, hamper) == 5
        assert _soh(db_conn, "C3") == -7      # -2 - 5
        assert _soh(db_conn, "C1") == -4      # 1 - 5
        assert _soh(db_conn, "C2") == 20

    def test_no_negative_soh_department_is_clamped_to_zero(self, hamper, db_conn):
        db_conn.execute("UPDATE departments SET no_negative_soh=1 WHERE id=(SELECT department_id FROM products WHERE barcode='C3')")
        db_conn.execute("UPDATE stock_on_hand SET quantity=1 WHERE barcode='C3'")
        db_conn.commit()
        kit_model.build(hamper, 3)
        assert _soh(db_conn, "C3") == 0
        assert _soh(db_conn, hamper) == 3

    def test_get_shortages_lists_components_that_wont_cover(self, hamper, db_conn):
        db_conn.execute("UPDATE stock_on_hand SET quantity=-1 WHERE barcode='C3'")
        db_conn.commit()
        short = kit_model.get_shortages(hamper, 2)
        assert [(x['description'], x['need'], x['have']) for x in short] == [("Gummies 250g", 2, -1)]
        assert kit_model.get_shortages(hamper, 1) != []
        assert kit_model.get_shortages("H1", 0) == []

    def test_no_recipe_and_zero_qty_rejected(self, db_conn, dept_id, hamper):
        _product(db_conn, dept_id, "P9", "Plain product", 1)
        with pytest.raises(ValueError, match="no components"):
            kit_model.build("P9", 1)
        with pytest.raises(ValueError):
            kit_model.build(hamper, 0)

    def test_build_is_logged(self, hamper):
        bid = kit_model.build(hamper, 3, notes="Xmas batch 1", created_by="ash")
        b = kit_model.get_builds(hamper)[0]
        assert b['id'] == bid and b['qty'] == 3 and b['notes'] == "Xmas batch 1"
        assert b['unit_cost'] == pytest.approx(30.5)


class TestBreakDown:
    def test_break_down_returns_components(self, hamper, db_conn):
        kit_model.build(hamper, 4)
        kit_model.build(hamper, -3)
        assert _soh(db_conn, hamper) == 1
        assert _soh(db_conn, "C1") == 9      # 10 -4 +3
        assert _soh(db_conn, "C2") == 28     # 30 -8 +6

    def test_cannot_break_down_more_than_on_hand(self, hamper, db_conn):
        kit_model.build(hamper, 1)
        with pytest.raises(ValueError, match="cannot break down"):
            kit_model.build(hamper, -2)
        assert _soh(db_conn, hamper) == 1
