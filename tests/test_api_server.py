"""Smoke tests for the Flask REST API (api_server.py).

Each test uses an isolated in-memory database via the shared test_db fixture.
The API key is generated into that DB by the server's own _get_api_key() so
the auth path is exercised end-to-end.
"""
import time
import pytest


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def api_client(test_db):
    """Flask test client with test DB wired and the server's generated API key."""
    import api_server
    api_server._sale_clients.clear()   # isolate rate-limiter state between tests
    api_server._read_clients.clear()
    api_server._api_key_cache = ""   # force key re-derivation from the fresh test DB
    api_server._api_key_refresh_ts = 0.0   # disarm the mismatch-refresh throttle
    app = api_server.app
    app.config["TESTING"] = True
    key = api_server._get_api_key()
    with app.test_client() as client:
        yield client, key


def _h(key):
    return {"X-API-Key": key}


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_no_auth_required(api_client):
    client, _ = api_client
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "BackOfficePro"


def test_health_returns_503_when_db_unavailable(api_client, monkeypatch):
    from unittest.mock import MagicMock
    import sqlite3
    import database.connection as db_conn
    client, _ = api_client

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.OperationalError("simulated db failure")
    monkeypatch.setattr(db_conn, "get_connection", lambda: mock_conn)

    r = client.get("/api/v1/health")
    assert r.status_code == 503
    data = r.get_json()
    assert data["status"] == "error"
    assert "detail" not in data


# ── Auth guard ────────────────────────────────────────────────────────────────

def test_missing_key_returns_401(api_client):
    client, _ = api_client
    r = client.get("/api/v1/store")
    assert r.status_code == 401


def test_wrong_key_returns_401(api_client):
    client, _ = api_client
    r = client.get("/api/v1/store", headers={"X-API-Key": "not-the-right-key"})
    assert r.status_code == 401


def test_key_via_query_param_rejected(api_client):
    """API key in query string is no longer accepted — header only."""
    client, key = api_client
    r = client.get(f"/api/v1/store?api_key={key}")
    assert r.status_code == 401


def test_key_via_header_accepted(api_client):
    client, key = api_client
    r = client.get("/api/v1/store", headers=_h(key))
    assert r.status_code == 200


def test_regenerated_key_accepted_without_restart(api_client):
    """A key rotated by the Settings screen (separate process) must work
    against the already-cached server without a restart."""
    from utils.api_key import store_api_key
    client, old_key = api_client
    new_key = "ab" * 32
    store_api_key(new_key)

    r = client.get("/api/v1/store", headers=_h(new_key))
    assert r.status_code == 200

    import api_server
    api_server._api_key_refresh_ts = 0.0   # past the throttle window
    r = client.get("/api/v1/store", headers=_h(old_key))
    assert r.status_code == 401


def test_mismatch_refresh_is_throttled(api_client):
    """Within the throttle window a rotated key is still rejected — the
    store must not be re-read on every bad request."""
    from utils.api_key import store_api_key
    client, old_key = api_client
    new_key = "cd" * 32
    store_api_key(new_key)

    import api_server
    api_server._api_key_refresh_ts = time.monotonic()   # refresh just happened
    r = client.get("/api/v1/store", headers=_h(new_key))
    assert r.status_code == 401

    api_server._api_key_refresh_ts = 0.0   # window elapsed — now picked up
    r = client.get("/api/v1/store", headers=_h(new_key))
    assert r.status_code == 200


# ── Request ID header ─────────────────────────────────────────────────────────

def test_request_id_header_present_on_success(api_client):
    client, key = api_client
    r = client.get("/api/v1/store", headers=_h(key))
    assert "X-Request-ID" in r.headers
    assert len(r.headers["X-Request-ID"]) == 8


def test_request_id_header_present_on_401(api_client):
    client, _ = api_client
    r = client.get("/api/v1/store")
    assert r.status_code == 401
    assert "X-Request-ID" in r.headers


def test_each_request_gets_unique_id(api_client):
    client, key = api_client
    ids = {client.get("/api/v1/health").headers.get("X-Request-ID") for _ in range(5)}
    assert len(ids) == 5   # all 5 requests got distinct IDs


# ── Store ─────────────────────────────────────────────────────────────────────

def test_store_returns_required_fields(api_client):
    client, key = api_client
    r = client.get("/api/v1/store", headers=_h(key))
    assert r.status_code == 200
    data = r.get_json()
    for field in ("store_name", "store_address", "store_phone", "store_abn", "gst_rate"):
        assert field in data, f"missing field: {field}"


# ── Departments ───────────────────────────────────────────────────────────────

def test_departments_returns_list(api_client):
    client, key = api_client
    r = client.get("/api/v1/departments", headers=_h(key))
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_departments_have_required_fields(api_client):
    client, key = api_client
    depts = client.get("/api/v1/departments", headers=_h(key)).get_json()
    for dept in depts:
        assert "id" in dept
        assert "code" in dept
        assert "name" in dept


def test_department_groups_returns_created_group(api_client, db_conn, dept_id):
    client, key = api_client
    db_conn.execute(
        "INSERT INTO product_groups (department_id, code, name) VALUES (?, 'FRUIT', 'Fruit')",
        (dept_id,)
    )
    db_conn.commit()

    r = client.get(f"/api/v1/departments/{dept_id}/groups", headers=_h(key))

    assert r.status_code == 200
    groups = r.get_json()
    assert any(g["code"] == "FRUIT" and g["name"] == "Fruit" for g in groups)


def test_department_groups_empty_for_unknown_department(api_client):
    client, key = api_client
    r = client.get("/api/v1/departments/99999/groups", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json() == []


# ── Products list ─────────────────────────────────────────────────────────────

def test_products_list_returns_list(api_client):
    client, key = api_client
    r = client.get("/api/v1/products", headers=_h(key))
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_products_invalid_limit_is_400(api_client):
    client, key = api_client
    r = client.get("/api/v1/products?limit=not_a_number", headers=_h(key))
    assert r.status_code == 400


def test_products_invalid_offset_is_400(api_client):
    client, key = api_client
    r = client.get("/api/v1/products?offset=xyz", headers=_h(key))
    assert r.status_code == 400


def test_products_search_returns_list(api_client, product_barcode):
    client, key = api_client
    r = client.get("/api/v1/products?search=Test+Product", headers=_h(key))
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


# ── Product by barcode ────────────────────────────────────────────────────────

def test_product_by_barcode_found(api_client, product_barcode):
    client, key = api_client
    r = client.get(f"/api/v1/products/{product_barcode}", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json()["barcode"] == product_barcode


def test_product_by_barcode_not_found(api_client):
    client, key = api_client
    r = client.get("/api/v1/products/0000000000000", headers=_h(key))
    assert r.status_code == 404


# ── Product by PLU ────────────────────────────────────────────────────────────

def test_product_by_plu_not_found(api_client):
    client, key = api_client
    r = client.get("/api/v1/products/plu/99999", headers=_h(key))
    assert r.status_code == 404


def test_product_by_plu_found(api_client, db_conn, product_barcode):
    client, key = api_client
    db_conn.execute(
        "INSERT INTO plu_barcode_map (plu, barcode) VALUES (12345, ?)", (product_barcode,)
    )
    db_conn.commit()

    r = client.get("/api/v1/products/plu/12345", headers=_h(key))

    assert r.status_code == 200
    assert r.get_json()["barcode"] == product_barcode


# ── Product image ─────────────────────────────────────────────────────────────

def test_product_image_not_found(api_client, product_barcode):
    client, key = api_client
    r = client.get(f"/api/v1/products/{product_barcode}/image", headers=_h(key))
    assert r.status_code == 404


def test_product_image_invalid_barcode_returns_400(api_client):
    client, key = api_client
    r = client.get("/api/v1/products/bad!barcode/image", headers=_h(key))
    assert r.status_code == 400


def test_product_image_delete_nonexistent_returns_ok(api_client, product_barcode):
    client, key = api_client
    r = client.delete(f"/api/v1/products/{product_barcode}/image", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json()["ok"] is False   # file did not exist


def test_product_image_delete_invalid_barcode_returns_400(api_client):
    client, key = api_client
    r = client.delete("/api/v1/products/bad!barcode/image", headers=_h(key))
    assert r.status_code == 400


# ── Stocktake sessions ────────────────────────────────────────────────────────

def test_sessions_list_initially_empty(api_client):
    client, key = api_client
    r = client.get("/api/v1/sessions", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json() == []


def test_session_create_returns_id(api_client):
    client, key = api_client
    r = client.post("/api/v1/sessions", json={"label": "Smoke Test"}, headers=_h(key))
    assert r.status_code == 201
    assert "id" in r.get_json()


def test_session_create_missing_label_is_400(api_client):
    client, key = api_client
    r = client.post("/api/v1/sessions", json={}, headers=_h(key))
    assert r.status_code == 400


def test_session_retrieve(api_client):
    client, key = api_client
    sid = client.post("/api/v1/sessions", json={"label": "Retrieve Me"}, headers=_h(key)).get_json()["id"]
    r = client.get(f"/api/v1/sessions/{sid}", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json()["label"] == "Retrieve Me"


def test_session_not_found_is_404(api_client):
    client, key = api_client
    r = client.get("/api/v1/sessions/99999", headers=_h(key))
    assert r.status_code == 404


# ── Counts ────────────────────────────────────────────────────────────────────

def test_counts_empty_for_new_session(api_client):
    client, key = api_client
    sid = client.post("/api/v1/sessions", json={"label": "Count Test"}, headers=_h(key)).get_json()["id"]
    r = client.get(f"/api/v1/sessions/{sid}/counts", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json() == []


def test_add_count_missing_fields_is_400(api_client):
    client, key = api_client
    sid = client.post("/api/v1/sessions", json={"label": "Count Test"}, headers=_h(key)).get_json()["id"]
    r = client.post(f"/api/v1/sessions/{sid}/counts", json={}, headers=_h(key))
    assert r.status_code == 400


def test_add_count_non_numeric_qty_is_400(api_client):
    client, key = api_client
    sid = client.post("/api/v1/sessions", json={"label": "Count Test"}, headers=_h(key)).get_json()["id"]
    r = client.post(
        f"/api/v1/sessions/{sid}/counts",
        json={"barcode": "0000000000000", "qty": "not-a-number"},
        headers=_h(key),
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "INVALID_PARAM"


def test_add_count_unknown_barcode_is_404(api_client):
    client, key = api_client
    sid = client.post("/api/v1/sessions", json={"label": "Count Test"}, headers=_h(key)).get_json()["id"]
    r = client.post(
        f"/api/v1/sessions/{sid}/counts",
        json={"barcode": "0000000000000", "qty": 5},
        headers=_h(key),
    )
    assert r.status_code == 404


def test_add_count_and_retrieve(api_client, product_barcode):
    client, key = api_client
    sid = client.post("/api/v1/sessions", json={"label": "Count Test"}, headers=_h(key)).get_json()["id"]

    r = client.post(
        f"/api/v1/sessions/{sid}/counts",
        json={"barcode": product_barcode, "qty": 12},
        headers=_h(key),
    )
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    r2 = client.get(f"/api/v1/sessions/{sid}/counts/barcode/{product_barcode}", headers=_h(key))
    assert r2.status_code == 200
    assert r2.get_json()["counted_qty"] == 12.0


def test_delete_count(api_client, product_barcode):
    client, key = api_client
    sid = client.post("/api/v1/sessions", json={"label": "Del Test"}, headers=_h(key)).get_json()["id"]
    client.post(
        f"/api/v1/sessions/{sid}/counts",
        json={"barcode": product_barcode, "qty": 3},
        headers=_h(key),
    )
    counts = client.get(f"/api/v1/sessions/{sid}/counts", headers=_h(key)).get_json()
    assert len(counts) == 1
    count_id = counts[0]["id"]

    r = client.delete(f"/api/v1/sessions/{sid}/counts/{count_id}", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    counts_after = client.get(f"/api/v1/sessions/{sid}/counts", headers=_h(key)).get_json()
    assert counts_after == []


# ── POS sale ──────────────────────────────────────────────────────────────────

def test_pos_sale_missing_required_fields_is_400(api_client):
    client, key = api_client
    r = client.post("/api/v1/pos/sale", json={}, headers=_h(key))
    assert r.status_code == 400


@pytest.mark.parametrize("bad_date", [
    "not-a-date",
    "29-01-2026",     # DD-MM-YYYY
    "2026/01/01",     # slashes
    "2026-13-01",     # month 13
    "2026-01-32",     # day 32
])
def test_pos_sale_invalid_date_is_400(api_client, bad_date):
    client, key = api_client
    r = client.post(
        "/api/v1/pos/sale",
        json={"reference": f"BAD-DATE-{bad_date}", "sale_date": bad_date,
              "items": [{"barcode": "x", "qty": 1, "line_total": 1.0}]},
        headers=_h(key),
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "INVALID_DATE"


def test_pos_sale_no_items_is_400(api_client):
    client, key = api_client
    r = client.post(
        "/api/v1/pos/sale",
        json={"reference": "REF-001", "sale_date": "2026-01-01", "items": []},
        headers=_h(key),
    )
    assert r.status_code == 400


def test_pos_sale_success(api_client, product_barcode):
    client, key = api_client
    payload = {
        "reference": "POS-SMOKE-0001",
        "sale_date": "2026-01-01",
        "operator": "test",
        "items": [{
            "barcode": product_barcode,
            "description": "Test Product",
            "qty": 1,
            "unit_price": 3.50,
            "line_total": 3.50,
            "tax_rate": 10.0,
        }],
    }
    r = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["reference"] == "POS-SMOKE-0001"
    assert data["duplicate"] is False


def test_pos_sale_idempotent_returns_200_not_500(api_client, product_barcode):
    """Retrying the same reference must return 200, not 500."""
    client, key = api_client
    payload = {
        "reference": "POS-IDEM-0001",
        "sale_date": "2026-01-01",
        "operator": "test",
        "items": [{
            "barcode": product_barcode,
            "description": "Test Product",
            "qty": 2,
            "unit_price": 3.50,
            "line_total": 7.00,
            "tax_rate": 10.0,
        }],
    }
    r1 = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r1.status_code == 200
    assert r1.get_json()["duplicate"] is False

    r2 = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r2.status_code == 200
    assert r2.get_json()["duplicate"] is True


def test_pos_sale_idempotent_does_not_double_decrement_soh(api_client, db_conn, product_barcode):
    """SOH must be decremented exactly once regardless of how many retries arrive."""
    client, key = api_client

    # Seed a known SOH so we can measure the decrement precisely.
    db_conn.execute(
        "INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, 10)"
        " ON CONFLICT(barcode) DO UPDATE SET quantity = 10",
        (product_barcode,),
    )
    db_conn.commit()

    payload = {
        "reference": "POS-IDEM-SOH-001",
        "sale_date": "2026-01-01",
        "operator": "test",
        "items": [{
            "barcode": product_barcode,
            "description": "Test Product",
            "qty": 3,
            "unit_price": 3.50,
            "line_total": 10.50,
            "tax_rate": 10.0,
        }],
    }
    client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    client.post("/api/v1/pos/sale", json=payload, headers=_h(key))

    row = db_conn.execute(
        "SELECT quantity FROM stock_on_hand WHERE barcode = ?", (product_barcode,)
    ).fetchone()
    assert row["quantity"] == 7.0   # 10 − 3 once, not thrice


def test_pos_sale_different_references_both_recorded(api_client, product_barcode):
    """Two different references from the same POS are both written independently."""
    client, key = api_client
    base = {
        "sale_date": "2026-01-01",
        "operator": "test",
        "items": [{
            "barcode": product_barcode,
            "description": "Test Product",
            "qty": 1,
            "unit_price": 3.50,
            "line_total": 3.50,
            "tax_rate": 10.0,
        }],
    }
    r1 = client.post("/api/v1/pos/sale", json={**base, "reference": "POS-A-001"}, headers=_h(key))
    r2 = client.post("/api/v1/pos/sale", json={**base, "reference": "POS-A-002"}, headers=_h(key))
    assert r1.get_json()["duplicate"] is False
    assert r2.get_json()["duplicate"] is False


def test_pos_sale_rate_limit(api_client):
    from collections import deque
    from api_server import _sale_clients, _SALE_MAX
    # Pre-fill the sliding window for 127.0.0.1 (Flask test-client IP)
    now = time.monotonic()
    _sale_clients["127.0.0.1"] = deque([now] * _SALE_MAX)

    client, key = api_client
    payload = {
        "reference": "RL-001",
        "sale_date": "2026-01-01",
        "operator": "test",
        "items": [{"barcode": "x", "qty": 1, "line_total": 1.0, "description": "x"}],
    }
    r = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r.status_code == 429


def test_read_rate_limit(api_client):
    from collections import deque
    from api_server import _read_clients, _READ_MAX
    now = time.monotonic()
    _read_clients["127.0.0.1"] = deque([now] * _READ_MAX)

    client, key = api_client
    r = client.get("/api/v1/store", headers=_h(key))
    assert r.status_code == 429


def test_rate_limiter_prunes_expired_entries(api_client):
    """An entry older than the sliding window must be pruned (popleft), not
    just left to count against the limit forever."""
    from collections import deque
    import api_server

    expired = time.monotonic() - api_server._SALE_WINDOW - 1
    api_server._sale_clients["9.9.9.9"] = deque([expired])

    assert api_server._sale_rate_ok("9.9.9.9") is True
    assert len(api_server._sale_clients["9.9.9.9"]) == 1  # only the fresh entry remains


def test_read_rate_limit_does_not_affect_pos_sale(api_client, product_barcode):
    """Filling the read window must not block /pos/sale, which has its own limiter."""
    from collections import deque
    from api_server import _read_clients, _READ_MAX
    now = time.monotonic()
    _read_clients["127.0.0.1"] = deque([now] * _READ_MAX)

    client, key = api_client
    payload = {
        "reference": "RL-READ-BYPASS-001",
        "sale_date": "2026-01-01",
        "operator": "test",
        "items": [{
            "barcode": product_barcode,
            "description": "Test Product",
            "qty": 1,
            "unit_price": 3.50,
            "line_total": 3.50,
            "tax_rate": 10.0,
        }],
    }
    r = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r.status_code == 200


# ── Bundles ───────────────────────────────────────────────────────────────────

def test_bundles_returns_list(api_client):
    client, key = api_client
    r = client.get("/api/v1/bundles", headers=_h(key))
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


# ── Product image endpoints ───────────────────────────────────────────────────

def test_get_product_image_404_when_no_image(api_client, product_barcode):
    client, key = api_client
    r = client.get(f"/api/v1/products/{product_barcode}/image", headers=_h(key))
    assert r.status_code == 404


def test_get_product_image_400_for_bad_barcode(api_client):
    client, key = api_client
    r = client.get("/api/v1/products/../../etc/passwd/image", headers=_h(key))
    assert r.status_code in (400, 404)


def test_delete_product_image_ok_when_no_image(api_client, product_barcode):
    client, key = api_client
    r = client.delete(f"/api/v1/products/{product_barcode}/image", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json()["ok"] is False


def test_get_product_image_serves_file(api_client, product_barcode, tmp_path, monkeypatch):
    import controllers.product_controller as pc
    img = tmp_path / f"{product_barcode}.jpg"
    img.write_bytes(b"FAKEJPEG")
    monkeypatch.setattr(pc, "find_product_image", lambda bc: str(img))
    client, key = api_client
    r = client.get(f"/api/v1/products/{product_barcode}/image", headers=_h(key))
    assert r.status_code == 200


# ── Products: limit/offset pagination ────────────────────────────────────────

def test_list_products_with_limit_offset(api_client):
    client, key = api_client
    r = client.get("/api/v1/products?limit=5&offset=0", headers=_h(key))
    assert r.status_code == 200


def test_list_products_invalid_limit_returns_400(api_client):
    client, key = api_client
    r = client.get("/api/v1/products?limit=abc", headers=_h(key))
    assert r.status_code == 400


# ── POS sale error paths ──────────────────────────────────────────────────────

def test_pos_sale_db_locked_returns_503(api_client, product_barcode, monkeypatch):
    import sqlite3
    import controllers.sales_report_controller as sr
    monkeypatch.setattr(
        sr, "record_pos_sale",
        lambda *a, **kw: (_ for _ in ()).throw(
            sqlite3.OperationalError("database is locked")
        ),
    )
    client, key = api_client
    payload = {
        "reference": "ERR-LOCK-001",
        "sale_date": "2026-05-01",
        "operator": "test",
        "items": [{"barcode": product_barcode, "qty": 1,
                   "unit_price": 3.50, "line_total": 3.50, "description": "X"}],
    }
    r = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r.status_code == 503


def test_pos_sale_generic_error_returns_500(api_client, product_barcode, monkeypatch):
    import controllers.sales_report_controller as sr
    monkeypatch.setattr(
        sr, "record_pos_sale",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    client, key = api_client
    payload = {
        "reference": "ERR-BOOM-001",
        "sale_date": "2026-05-01",
        "operator": "test",
        "items": [{"barcode": product_barcode, "qty": 1,
                   "unit_price": 3.50, "line_total": 3.50, "description": "X"}],
    }
    r = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r.status_code == 500


def test_pos_sale_non_lock_operational_error_returns_500(api_client, product_barcode, monkeypatch):
    """An sqlite3.OperationalError NOT about a lock (e.g. schema drift) is a
    distinct branch from the 'database is locked' 503 path — also 500."""
    import sqlite3
    import controllers.sales_report_controller as sr
    monkeypatch.setattr(
        sr, "record_pos_sale",
        lambda *a, **kw: (_ for _ in ()).throw(
            sqlite3.OperationalError("no such table: sales_daily")
        ),
    )
    client, key = api_client
    payload = {
        "reference": "ERR-SCHEMA-001",
        "sale_date": "2026-05-01",
        "operator": "test",
        "items": [{"barcode": product_barcode, "qty": 1,
                   "unit_price": 3.50, "line_total": 3.50, "description": "X"}],
    }
    r = client.post("/api/v1/pos/sale", json=payload, headers=_h(key))
    assert r.status_code == 500
    assert r.get_json()["error"] == "SALE_ERROR"


# ── add_count edge cases ──────────────────────────────────────────────────────

def test_add_count_qty_over_limit_returns_400(api_client, db_conn, supplier_id, product_barcode):
    import controllers.stocktake_controller as st_ctrl
    session_id = st_ctrl.create_session("Test")
    client, key = api_client
    r = client.post(
        f"/api/v1/sessions/{session_id}/counts",
        json={"barcode": product_barcode, "qty": 100000},
        headers=_h(key),
    )
    assert r.status_code == 400


def test_add_count_product_not_found_returns_404(api_client, db_conn, supplier_id):
    import controllers.stocktake_controller as st_ctrl
    session_id = st_ctrl.create_session("Test2")
    client, key = api_client
    r = client.post(
        f"/api/v1/sessions/{session_id}/counts",
        json={"barcode": "0000000000000", "qty": 1},
        headers=_h(key),
    )
    assert r.status_code == 404


# ── _get_api_key double-checked locking ──────────────────────────────────────

def test_get_api_key_fast_path_returns_cached(api_client):
    import api_server
    key1 = api_server._get_api_key()
    key2 = api_server._get_api_key()
    assert key1 == key2 and len(key1) > 0


# ── Bundles with eligible items ───────────────────────────────────────────────

def test_bundles_with_eligible_items(api_client, db_conn, product_barcode):
    from controllers.bundle_controller import create as create_bundle
    from controllers.bundle_controller import add_eligible
    bundle_id = create_bundle("Test Bundle", "", 4, 12.00)
    add_eligible(bundle_id, product_barcode, "Test Product", unit_qty=1)
    client, key = api_client
    r = client.get("/api/v1/bundles", headers=_h(key))
    assert r.status_code == 200
    bundles = r.get_json()
    b = next((b for b in bundles if b["id"] == bundle_id), None)
    assert b is not None
    assert len(b["eligible"]) == 1


# ── Internals: API key double-checked locking, teardown ───────────────────────

def test_teardown_closes_thread_connection_when_not_testing(api_client, monkeypatch):
    """In real (non-TESTING) operation, the teardown handler must release the
    per-request DB connection via close_thread_connection()."""
    import api_server
    import database.connection as conn_mod

    called = []
    monkeypatch.setattr(conn_mod, "close_thread_connection", lambda: called.append(1))

    client, key = api_client
    api_server.app.config["TESTING"] = False
    try:
        r = client.get("/api/v1/health", headers=_h(key))
        assert r.status_code == 200
    finally:
        api_server.app.config["TESTING"] = True

    assert called == [1]


def test_concurrent_api_key_resolution_only_resolves_once(test_db, monkeypatch):
    """Double-checked locking: a second thread arriving while the first is
    still resolving the key must see the cache already populated (hit the
    inner re-check) rather than resolving it again."""
    import threading
    import api_server
    import utils.api_key as api_key_mod

    api_server._api_key_cache = ""
    call_count = {"n": 0}
    started  = threading.Event()
    proceed  = threading.Event()

    def slow_resolve():
        call_count["n"] += 1
        started.set()
        proceed.wait(timeout=2)
        return "resolved-key-123"

    monkeypatch.setattr(api_key_mod, "resolve_api_key", slow_resolve)

    results = []
    t1 = threading.Thread(target=lambda: results.append(api_server._get_api_key()))
    t1.start()
    assert started.wait(timeout=2), "thread 1 never entered resolve_api_key"

    t2 = threading.Thread(target=lambda: results.append(api_server._get_api_key()))
    t2.start()
    time.sleep(0.05)  # give thread 2 a moment to block on the lock
    proceed.set()

    t1.join(timeout=2)
    t2.join(timeout=2)

    assert results == ["resolved-key-123", "resolved-key-123"]
    assert call_count["n"] == 1, "resolve_api_key should only run once for concurrent callers"
