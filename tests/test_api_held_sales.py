"""Tests for the held-sales API routes (POS suspend/resume-sale feature).

  POST /api/v1/held-sales
  GET  /api/v1/held-sales
  GET  /api/v1/held-sales/<reference>
  POST /api/v1/held-sales/<reference>/resume
  POST /api/v1/held-sales/<reference>/void
"""
import pytest


@pytest.fixture()
def api_client(test_db):
    import api_server
    api_server._sale_clients.clear()
    api_server._read_clients.clear()
    api_server._api_key_cache = ""
    api_server.app.config["TESTING"] = True
    key = api_server._get_api_key()
    with api_server.app.test_client() as client:
        yield client, key


def _h(key):
    return {"X-API-Key": key}


def _hold_body(terminal_id="POS-001", operator="ashley"):
    return {
        "terminal_id": terminal_id, "operator": operator, "note": "",
        "subtotal": 9.09, "gst_amount": 0.91, "total": 10.00,
        "items": [{"barcode": "9300000000001", "description": "Test Product",
                   "qty": 2, "unit_price": 5.00, "tax_rate": 10.0, "price_reason": ""}],
    }


# ── POST /api/v1/held-sales ─────────────────────────────────────────────────

def test_create_hold_returns_reference(api_client):
    client, key = api_client
    r = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body())
    assert r.status_code == 201
    assert r.get_json()["reference"].startswith("HLD-")


def test_create_hold_missing_terminal_id_400(api_client):
    client, key = api_client
    body = _hold_body()
    body["terminal_id"] = ""
    r = client.post("/api/v1/held-sales", headers=_h(key), json=body)
    assert r.status_code == 400


def test_create_hold_missing_items_400(api_client):
    client, key = api_client
    body = _hold_body()
    body["items"] = []
    r = client.post("/api/v1/held-sales", headers=_h(key), json=body)
    assert r.status_code == 400


def test_create_hold_without_api_key_401(api_client):
    client, key = api_client
    r = client.post("/api/v1/held-sales", json=_hold_body())
    assert r.status_code == 401


# ── GET /api/v1/held-sales ───────────────────────────────────────────────────

def test_list_holds_empty_when_none_open(api_client):
    client, key = api_client
    r = client.get("/api/v1/held-sales", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json() == []


def test_list_holds_returns_open_hold(api_client):
    client, key = api_client
    client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body())
    r = client.get("/api/v1/held-sales", headers=_h(key))
    data = r.get_json()
    assert len(data) == 1
    assert data[0]["terminal_id"] == "POS-001"
    assert data[0]["item_count"] == 1


def test_list_holds_excludes_resumed(api_client):
    client, key = api_client
    created = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body()).get_json()
    client.post(f"/api/v1/held-sales/{created['reference']}/resume",
               headers=_h(key), json={"terminal_id": "POS-002"})
    r = client.get("/api/v1/held-sales", headers=_h(key))
    assert r.get_json() == []


# ── GET /api/v1/held-sales/<reference> ───────────────────────────────────────

def test_get_hold_returns_full_basket(api_client):
    client, key = api_client
    created = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body()).get_json()
    r = client.get(f"/api/v1/held-sales/{created['reference']}", headers=_h(key))
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["lines"]) == 1
    assert data["lines"][0]["barcode"] == "9300000000001"


def test_get_hold_unknown_reference_404(api_client):
    client, key = api_client
    r = client.get("/api/v1/held-sales/HLD-99999", headers=_h(key))
    assert r.status_code == 404


# ── POST /api/v1/held-sales/<reference>/resume ───────────────────────────────

def test_resume_hold_succeeds_and_returns_lines(api_client):
    client, key = api_client
    created = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body()).get_json()
    r = client.post(f"/api/v1/held-sales/{created['reference']}/resume",
                    headers=_h(key), json={"terminal_id": "POS-002"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "RESUMED"
    assert len(data["lines"]) == 1


def test_resume_hold_twice_returns_409(api_client):
    client, key = api_client
    created = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body()).get_json()
    client.post(f"/api/v1/held-sales/{created['reference']}/resume",
               headers=_h(key), json={"terminal_id": "POS-002"})
    r = client.post(f"/api/v1/held-sales/{created['reference']}/resume",
                    headers=_h(key), json={"terminal_id": "POS-003"})
    assert r.status_code == 409
    assert r.get_json()["error"] == "INVALID_STATUS"


def test_resume_hold_unknown_reference_404(api_client):
    client, key = api_client
    r = client.post("/api/v1/held-sales/HLD-99999/resume",
                    headers=_h(key), json={"terminal_id": "POS-002"})
    assert r.status_code == 404


def test_resume_hold_missing_terminal_id_400(api_client):
    client, key = api_client
    created = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body()).get_json()
    r = client.post(f"/api/v1/held-sales/{created['reference']}/resume",
                    headers=_h(key), json={})
    assert r.status_code == 400


# ── POST /api/v1/held-sales/<reference>/void ─────────────────────────────────

def test_void_hold_succeeds(api_client):
    client, key = api_client
    created = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body()).get_json()
    r = client.post(f"/api/v1/held-sales/{created['reference']}/void", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json()["status"] == "VOIDED"


def test_resume_after_void_returns_409(api_client):
    client, key = api_client
    created = client.post("/api/v1/held-sales", headers=_h(key), json=_hold_body()).get_json()
    client.post(f"/api/v1/held-sales/{created['reference']}/void", headers=_h(key))
    r = client.post(f"/api/v1/held-sales/{created['reference']}/resume",
                    headers=_h(key), json={"terminal_id": "POS-002"})
    assert r.status_code == 409


def test_void_hold_unknown_reference_404(api_client):
    client, key = api_client
    r = client.post("/api/v1/held-sales/HLD-99999/void", headers=_h(key))
    assert r.status_code == 404
