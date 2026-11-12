"""Tests for utils/shop_sync.py - pushing Harcourt Cider catalogue changes to the web shop."""
import gzip
import json
import sqlite3

import pytest

from utils import shop_sync

# Columns the shop's catalogue endpoint requires (HarcourtCiderShop/catalogue.py REQUIRED).
SHOP_REQUIRED = {
    "products": {"barcode", "description", "brand", "sell_price", "tax_rate", "unit",
                 "variable_weight", "weight_grams", "active", "online_available",
                 "online_notes", "department_id", "group_id"},
    "product_groups": {"id", "name"},
}


@pytest.fixture()
def store_db(tmp_path):
    path = tmp_path / "harcourt_cider.db"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE product_groups (id INTEGER PRIMARY KEY, department_id INT, name TEXT, code TEXT);
        CREATE TABLE products (
            barcode TEXT PRIMARY KEY, description TEXT, brand TEXT DEFAULT '', sell_price REAL,
            cost_price REAL, supplier_id INT, tax_rate REAL DEFAULT 10, unit TEXT DEFAULT 'EA',
            variable_weight INT DEFAULT 0, weight_grams INT DEFAULT 0, active INT DEFAULT 1,
            online_available INT DEFAULT 0, online_notes TEXT, department_id INT DEFAULT 9, group_id INT);
        CREATE TABLE users (username TEXT, pin_hash TEXT);
        INSERT INTO users VALUES ('hc_admin', 'secrethash');
        INSERT INTO product_groups VALUES (29, 9, 'Cider BOTTLE', 'B');
        INSERT INTO products (barcode, description, sell_price, cost_price, online_available, group_id)
            VALUES ('111', 'Apple Cider CASE', 105, 61.5, 1, 29),
                   ('222', 'Not online',       5,   2,    0, 29);
    """)
    c.commit()
    c.close()
    return str(path)


def edit(db, sql, *params):
    c = sqlite3.connect(db)
    c.execute(sql, params)
    c.commit()
    c.close()


class TestConfig:
    def write(self, tmp_path, **cfg):
        (tmp_path / "shop_sync.json").write_text(json.dumps(cfg))

    def test_off_by_default(self, tmp_path):
        assert shop_sync.load_config(str(tmp_path), environ={}) is None

    def test_loads_file(self, tmp_path):
        self.write(tmp_path, url="https://shop.example/", token="t")
        c = shop_sync.load_config(str(tmp_path), environ={})
        assert c.url == "https://shop.example" and c.token == "t"
        assert c.db_path.endswith("harcourt_cider.db")

    def test_env_overrides_file(self, tmp_path):
        self.write(tmp_path, url="https://a.example", token="a")
        c = shop_sync.load_config(str(tmp_path), environ={"SHOP_SYNC_URL": "https://b.example",
                                                           "SHOP_SYNC_TOKEN": "b"})
        assert (c.url, c.token) == ("https://b.example", "b")

    def test_refuses_plain_http_to_internet(self, tmp_path):
        self.write(tmp_path, url="http://shop.example", token="t")
        assert shop_sync.load_config(str(tmp_path), environ={}) is None

    def test_allows_localhost_http(self, tmp_path):
        self.write(tmp_path, url="http://localhost:5002", token="t")
        assert shop_sync.load_config(str(tmp_path), environ={}) is not None

    def test_corrupt_file_means_off(self, tmp_path):
        (tmp_path / "shop_sync.json").write_text("{nope")
        assert shop_sync.load_config(str(tmp_path), environ={}) is None


class TestSnapshot:
    def open_snapshot(self, tmp_path, data):
        p = tmp_path / "out.db"
        p.write_bytes(gzip.decompress(data))
        return sqlite3.connect(p)

    def test_contains_only_online_products(self, store_db, tmp_path):
        data, n = shop_sync.build_snapshot(store_db)
        assert n == 1
        c = self.open_snapshot(tmp_path, data)
        assert [r[0] for r in c.execute("SELECT barcode FROM products")] == ["111"]
        assert c.execute("SELECT sell_price FROM products").fetchone()[0] == 105

    def test_no_sensitive_data_leaves_the_building(self, store_db, tmp_path):
        data, _ = shop_sync.build_snapshot(store_db)
        c = self.open_snapshot(tmp_path, data)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"products", "product_groups"}
        cols = {r[1] for r in c.execute("PRAGMA table_info(products)")}
        assert "cost_price" not in cols and "supplier_id" not in cols

    def test_satisfies_shop_endpoint_requirements(self, store_db, tmp_path):
        data, _ = shop_sync.build_snapshot(store_db)
        c = self.open_snapshot(tmp_path, data)
        for table, needed in SHOP_REQUIRED.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            assert needed <= have, (table, needed - have)
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    def test_source_database_untouched(self, store_db):
        before = open(store_db, "rb").read()
        shop_sync.build_snapshot(store_db)
        assert open(store_db, "rb").read() == before


class TestFingerprint:
    def test_changes_when_shop_visible_data_changes(self, store_db):
        a = shop_sync.fingerprint(store_db)
        edit(store_db, "UPDATE products SET sell_price=110 WHERE barcode='111'")
        assert shop_sync.fingerprint(store_db) != a

    def test_ticking_online_shop_changes_it(self, store_db):
        a = shop_sync.fingerprint(store_db)
        edit(store_db, "UPDATE products SET online_available=1 WHERE barcode='222'")
        assert shop_sync.fingerprint(store_db) != a

    @pytest.mark.parametrize("sql", [
        "UPDATE products SET cost_price=70 WHERE barcode='111'",          # shop doesn't show cost
        "UPDATE products SET sell_price=99 WHERE barcode='222'",          # not on the shop
    ])
    def test_unrelated_edits_do_not_trigger(self, store_db, sql):
        a = shop_sync.fingerprint(store_db)
        edit(store_db, sql)
        assert shop_sync.fingerprint(store_db) == a


class TestWatcher:
    def make(self, store_db, push_fn):
        cfg = shop_sync.SyncConfig("https://shop.example", "t", store_db, poll=0, settle=0)
        return shop_sync.ShopSyncWatcher(cfg, push_fn=push_fn)

    def test_no_push_at_startup_then_push_on_change(self, store_db):
        calls = []
        w = self.make(store_db, lambda cfg: calls.append(1))
        assert w.check_once(settle=False) == "baseline"
        assert w.check_once(settle=False) == "unchanged" and not calls
        edit(store_db, "UPDATE products SET sell_price=111 WHERE barcode='111'")
        assert w.check_once(settle=False) == "pushed" and calls == [1]
        assert w.check_once(settle=False) == "unchanged" and calls == [1]   # not pushed twice

    def test_failed_push_is_retried_until_it_works(self, store_db):
        outcomes = [RuntimeError("offline"), RuntimeError("offline"), None]
        def flaky(cfg):
            o = outcomes.pop(0)
            if o: raise o
        w = self.make(store_db, flaky)
        w.check_once(settle=False)
        edit(store_db, "UPDATE products SET sell_price=111 WHERE barcode='111'")
        assert w.check_once(settle=False) == "failed" and w._backoff >= 10
        assert w.check_once(settle=False) == "failed"
        assert w.check_once(settle=False) == "pushed" and w._backoff == 0
        assert w.check_once(settle=False) == "unchanged"

    def test_unreadable_db_does_not_crash(self, tmp_path):
        w = self.make(str(tmp_path / "missing.db"), lambda cfg: None)
        assert w.check_once(settle=False) == "failed"


class TestPush:
    def test_rejection_message_surfaces(self, monkeypatch):
        import requests
        class R:
            status_code, text = 401, "x"
            def json(self): return {"ok": False, "error": "bad token"}
        monkeypatch.setattr(requests, "post", lambda *a, **k: R())
        cfg = shop_sync.SyncConfig("https://s", "t", "x")
        with pytest.raises(RuntimeError, match="bad token"):
            shop_sync.push(cfg, b"x")

    def test_sends_token_and_url(self, monkeypatch):
        import requests
        seen = {}
        class R:
            status_code = 200
            def json(self): return {"ok": True, "products": 1}
        def fake(url, **kw): seen.update(url=url, **kw); return R()
        monkeypatch.setattr(requests, "post", fake)
        shop_sync.push(shop_sync.SyncConfig("https://s.example/", "tok", "x"), b"data")
        assert seen["url"] == "https://s.example/api/catalogue"
        assert seen["headers"]["X-Catalogue-Token"] == "tok" and seen["data"] == b"data"
