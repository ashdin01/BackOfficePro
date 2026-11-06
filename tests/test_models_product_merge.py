import pytest
from models import product_merge as pm


def _mk(db_conn, dept_id, barcode, desc, price=5.0, soh=0):
    db_conn.execute(
        "INSERT INTO products (barcode, description, department_id, sell_price, cost_price, active)"
        " VALUES (?,?,?,?,?,1)", (barcode, desc, dept_id, price, 1.0))
    db_conn.execute("INSERT OR REPLACE INTO stock_on_hand (barcode, quantity) VALUES (?,?)", (barcode, soh))
    db_conn.commit()


def _ids(db_conn, dept_id):
    _mk(db_conn, dept_id, "DUP1", "ZZ Duplicate", price=9.0, soh=4)
    _mk(db_conn, dept_id, "KEEP", "Keeper", price=5.0, soh=6)
    return "DUP1", "KEEP"


def test_every_barcode_table_is_handled(test_db, db_conn):
    tables = [r[0] for r in db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    missing = []
    for t in tables:
        cols = [r[1] for r in db_conn.execute(f"PRAGMA table_info({t})")]
        if any("barcode" in c for c in cols) and t not in pm.HANDLED_TABLES:
            missing.append(t)
    assert not missing, f"product_merge does not handle: {missing}"


def test_merge_moves_everything_keeps_keeper_details(test_db, db_conn, dept_id, supplier_id):
    dup, keep = _ids(db_conn, dept_id)
    db_conn.execute("INSERT INTO stock_movements (barcode, movement_type, quantity) VALUES (?, 'SALE', -1)", (dup,))
    db_conn.execute("INSERT INTO barcode_aliases (alias_barcode, master_barcode) VALUES (?,?)", (dup, dup))
    db_conn.execute("INSERT INTO barcode_aliases (alias_barcode, master_barcode) VALUES ('OLDALIAS', ?)", (dup,))
    db_conn.execute("INSERT INTO product_suppliers (barcode, supplier_id, is_default) VALUES (?,?,1)", (dup, supplier_id))
    db_conn.commit()
    pm.merge(dup, keep, user="tester")

    assert db_conn.execute("SELECT 1 FROM products WHERE barcode=?", (dup,)).fetchone() is None
    k = db_conn.execute("SELECT description, sell_price FROM products WHERE barcode=?", (keep,)).fetchone()
    assert (k["description"], k["sell_price"]) == ("Keeper", 5.0)
    assert db_conn.execute("SELECT quantity FROM stock_on_hand WHERE barcode=?", (keep,)).fetchone()[0] == 10
    assert db_conn.execute("SELECT COUNT(*) FROM stock_movements WHERE barcode=?", (keep,)).fetchone()[0] == 1
    aliases = {r["alias_barcode"]: r["master_barcode"] for r in db_conn.execute("SELECT * FROM barcode_aliases")}
    assert aliases == {dup: keep, "OLDALIAS": keep}
    assert db_conn.execute("SELECT COUNT(*) FROM product_suppliers WHERE barcode=?", (keep,)).fetchone()[0] == 1
    # scanning the old barcode now resolves to the keeper
    assert pm.resolve_target(dup)["barcode"] == keep
    assert db_conn.execute("SELECT COUNT(*) FROM audit_log WHERE entity_key=?", (keep,)).fetchone()[0] >= 1


def test_supplier_link_clash_keeps_keepers_default(test_db, db_conn, dept_id, supplier_id):
    dup, keep = _ids(db_conn, dept_id)
    db_conn.execute("INSERT INTO product_suppliers (barcode, supplier_id, is_default, supplier_sku) VALUES (?,?,1,'K')", (keep, supplier_id))
    db_conn.execute("INSERT INTO product_suppliers (barcode, supplier_id, is_default, supplier_sku) VALUES (?,?,1,'D')", (dup, supplier_id))
    db_conn.commit()
    pm.merge(dup, keep)
    rows = db_conn.execute("SELECT supplier_sku FROM product_suppliers WHERE barcode=?", (keep,)).fetchall()
    assert [r[0] for r in rows] == ["K"]


def test_stocktake_counts_summed_on_clash(test_db, db_conn, dept_id):
    dup, keep = _ids(db_conn, dept_id)
    cols = [r[1] for r in db_conn.execute("PRAGMA table_info(stocktake_sessions)") if r[3] and r[4] is None and r[1] != "id"]
    db_conn.execute("INSERT INTO stocktake_sessions DEFAULT VALUES") if not cols else \
        db_conn.execute(f"INSERT INTO stocktake_sessions ({','.join(cols)}) VALUES ({','.join(repr('x') for _ in cols)})")
    sid = db_conn.execute("SELECT MAX(id) FROM stocktake_sessions").fetchone()[0]
    db_conn.execute("INSERT INTO stocktake_counts (session_id, barcode, counted_qty) VALUES (?,?,3)", (sid, dup))
    db_conn.execute("INSERT INTO stocktake_counts (session_id, barcode, counted_qty) VALUES (?,?,2)", (sid, keep))
    db_conn.commit()
    pm.merge(dup, keep)
    rows = db_conn.execute("SELECT barcode, counted_qty FROM stocktake_counts").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(keep, 5)]


def test_refuses_self_kit_and_selling_units(test_db, db_conn, dept_id):
    dup, keep = _ids(db_conn, dept_id)
    with pytest.raises(ValueError, match="itself"):
        pm.merge(dup, dup)
    db_conn.execute("INSERT INTO product_selling_units (master_barcode, label, unit_qty) VALUES (?, 'Case', 24)", (dup,))
    db_conn.commit()
    with pytest.raises(ValueError, match="selling units"):
        pm.merge(dup, keep)
    db_conn.execute("DELETE FROM product_selling_units")
    db_conn.execute("INSERT INTO kit_components (parent_barcode, component_barcode, qty) VALUES (?,?,1)", (keep, dup))
    db_conn.commit()
    with pytest.raises(ValueError, match="kit"):
        pm.merge(dup, keep)
    # nothing changed on refusal
    assert db_conn.execute("SELECT quantity FROM stock_on_hand WHERE barcode=?", (keep,)).fetchone()[0] == 6


def test_failure_rolls_back(test_db, db_conn, dept_id, monkeypatch):
    dup, keep = _ids(db_conn, dept_id)
    from models import audit_log
    monkeypatch.setattr(audit_log, "_write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        pm.merge(dup, keep)
    assert db_conn.execute("SELECT 1 FROM products WHERE barcode=?", (dup,)).fetchone() is not None
    assert db_conn.execute("SELECT quantity FROM stock_on_hand WHERE barcode=?", (keep,)).fetchone()[0] == 6


def test_resolve_by_plu_and_preview(test_db, db_conn, dept_id):
    dup, keep = _ids(db_conn, dept_id)
    db_conn.execute("UPDATE products SET plu='68' WHERE barcode=?", (keep,))
    db_conn.commit()
    assert pm.resolve_target("068")["barcode"] == keep
    p = pm.preview(dup, keep)
    assert p["dup_soh"] == 4 and p["keeper_soh"] == 6


def test_controller_takes_backup_first(test_db, db_conn, dept_id, monkeypatch):
    import controllers.product_controller as pc
    from controllers import backup_controller as bc
    dup, keep = _ids(db_conn, dept_id)
    calls = []
    monkeypatch.setattr(bc, "pre_merge_backup", lambda: calls.append("backup"))
    pc.merge_products(dup, keep)
    assert calls == ["backup"]
    assert db_conn.execute("SELECT 1 FROM products WHERE barcode=?", (dup,)).fetchone() is None
