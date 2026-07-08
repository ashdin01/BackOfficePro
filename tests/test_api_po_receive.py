"""Tests for the PO-receiving API routes added for the mobile receive app.

  GET  /api/v1/purchase-orders
  GET  /api/v1/purchase-orders/<po_number>
  POST /api/v1/purchase-orders/<po_id>/receive
"""
import pytest
import controllers.purchase_order_controller as po_ctrl
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.stock_on_hand as soh_model


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


@pytest.fixture()
def sent_po(test_db, supplier_id, product_barcode):
    """SENT PO with one product line (10 cartons, pack_qty=6)."""
    po_id = po_ctrl.create_po(supplier_id, delivery_date="2026-07-01")
    po_ctrl.update_po_status(po_id, "SENT")
    po = po_ctrl.get_po_by_id(po_id)
    lines_model.add(po_id, product_barcode, "Test Product", 10, 2.50, "", 6)
    line = lines_model.get_by_po(po_id)[0]
    return {"po_id": po_id, "po_number": po["po_number"], "line": line}


@pytest.fixture()
def sent_po_two_lines(test_db, supplier_id, product_barcode, db_conn):
    """SENT PO with two product lines plus one note line."""
    bc2 = "9300000000099"
    dept = db_conn.execute("SELECT id FROM departments WHERE code='GROC'").fetchone()
    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, supplier_id,
            sell_price, cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, 'Second Product', ?, ?, 5.00, 3.00, 10.0, 1, 'EA', 1, 'EA')
    """, (bc2, dept["id"], supplier_id))
    db_conn.commit()

    po_id = po_ctrl.create_po(supplier_id, delivery_date="2026-07-01")
    po_ctrl.update_po_status(po_id, "SENT")
    po = po_ctrl.get_po_by_id(po_id)
    lines_model.add(po_id, product_barcode, "Test Product", 10, 2.50, "", 6)
    lines_model.add(po_id, bc2, "Second Product", 5, 3.00, "", 1)
    lines_model.add_note(po_id, "Delivery note: call before 9am")
    all_lines = [l for l in lines_model.get_by_po(po_id) if not l["is_note"]]
    return {"po_id": po_id, "po_number": po["po_number"],
            "lines": all_lines, "bc2": bc2}


# ── GET /api/v1/purchase-orders ───────────────────────────────────────────────

def test_list_pos_empty_when_none_sent(api_client, test_db):
    client, key = api_client
    r = client.get("/api/v1/purchase-orders", headers=_h(key))
    assert r.status_code == 200
    assert r.get_json() == []


def test_list_pos_returns_sent_po(api_client, sent_po):
    client, key = api_client
    r = client.get("/api/v1/purchase-orders", headers=_h(key))
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 1
    assert data[0]["po_number"] == sent_po["po_number"]
    assert data[0]["status"] == "SENT"


def test_list_pos_returns_partial_po(api_client, test_db, supplier_id):
    po_id = po_ctrl.create_po(supplier_id)
    po_ctrl.update_po_status(po_id, "PARTIAL")
    client, key = api_client
    data = client.get("/api/v1/purchase-orders", headers=_h(key)).get_json()
    assert any(d["status"] == "PARTIAL" for d in data)


def test_list_pos_excludes_draft_and_received(api_client, test_db, supplier_id):
    po_ctrl.create_po(supplier_id)                          # DRAFT
    received_id = po_ctrl.create_po(supplier_id)
    po_ctrl.update_po_status(received_id, "RECEIVED")
    client, key = api_client
    data = client.get("/api/v1/purchase-orders", headers=_h(key)).get_json()
    statuses = {d["status"] for d in data}
    assert "DRAFT" not in statuses
    assert "RECEIVED" not in statuses


def test_list_pos_has_required_fields(api_client, sent_po):
    client, key = api_client
    po = client.get("/api/v1/purchase-orders", headers=_h(key)).get_json()[0]
    for field in ("id", "po_number", "supplier_name", "status",
                  "delivery_date", "created_at", "line_count"):
        assert field in po, f"missing field: {field}"


def test_list_pos_line_count_excludes_notes(api_client, sent_po_two_lines):
    client, key = api_client
    data = client.get("/api/v1/purchase-orders", headers=_h(key)).get_json()
    po = next(d for d in data if d["po_number"] == sent_po_two_lines["po_number"])
    assert po["line_count"] == 2  # note line not counted


def test_list_pos_requires_auth(api_client):
    client, _ = api_client
    assert client.get("/api/v1/purchase-orders").status_code == 401


# ── GET /api/v1/purchase-orders/<po_number> ───────────────────────────────────

def test_get_po_detail_not_found(api_client):
    client, key = api_client
    r = client.get("/api/v1/purchase-orders/PO-99999", headers=_h(key))
    assert r.status_code == 404
    assert r.get_json()["error"] == "NOT_FOUND"


def test_get_po_detail_returns_po_fields(api_client, sent_po):
    client, key = api_client
    r = client.get(f"/api/v1/purchase-orders/{sent_po['po_number']}", headers=_h(key))
    assert r.status_code == 200
    data = r.get_json()
    for field in ("id", "po_number", "supplier_name", "status",
                  "delivery_date", "created_at", "lines"):
        assert field in data, f"missing field: {field}"
    assert data["po_number"] == sent_po["po_number"]
    assert data["status"] == "SENT"


def test_get_po_detail_lines_have_required_fields(api_client, sent_po):
    client, key = api_client
    data = client.get(
        f"/api/v1/purchase-orders/{sent_po['po_number']}", headers=_h(key)
    ).get_json()
    line = data["lines"][0]
    for field in ("id", "barcode", "description", "ordered_qty",
                  "pack_qty", "ordered_units", "received_qty", "unit_cost"):
        assert field in line, f"missing line field: {field}"


def test_get_po_detail_ordered_units_is_qty_times_pack(api_client, sent_po):
    client, key = api_client
    line = client.get(
        f"/api/v1/purchase-orders/{sent_po['po_number']}", headers=_h(key)
    ).get_json()["lines"][0]
    assert line["ordered_units"] == line["ordered_qty"] * line["pack_qty"]


def test_get_po_detail_excludes_note_lines(api_client, sent_po_two_lines):
    client, key = api_client
    data = client.get(
        f"/api/v1/purchase-orders/{sent_po_two_lines['po_number']}", headers=_h(key)
    ).get_json()
    assert len(data["lines"]) == 2
    for line in data["lines"]:
        assert line["barcode"] is not None


def test_get_po_detail_case_insensitive(api_client, sent_po):
    client, key = api_client
    lower = sent_po["po_number"].lower()
    r = client.get(f"/api/v1/purchase-orders/{lower}", headers=_h(key))
    assert r.status_code == 200


def test_get_po_detail_requires_auth(api_client, sent_po):
    client, _ = api_client
    r = client.get(f"/api/v1/purchase-orders/{sent_po['po_number']}")
    assert r.status_code == 401


# ── POST /api/v1/purchase-orders/<po_id>/receive ─────────────────────────────

def test_receive_po_not_found(api_client):
    client, key = api_client
    r = client.post("/api/v1/purchase-orders/999999/receive",
                    json={"lines": [{"line_id": 1, "received_qty": 1}]},
                    headers=_h(key))
    assert r.status_code == 404


def test_receive_draft_po_returns_409(api_client, test_db, supplier_id):
    po_id = po_ctrl.create_po(supplier_id)  # status = DRAFT
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{po_id}/receive",
                    json={"lines": [{"line_id": 1, "received_qty": 1}]},
                    headers=_h(key))
    assert r.status_code == 409
    assert r.get_json()["error"] == "INVALID_STATUS"


def test_receive_already_received_po_returns_409(api_client, test_db, supplier_id):
    po_id = po_ctrl.create_po(supplier_id)
    po_ctrl.update_po_status(po_id, "RECEIVED")
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{po_id}/receive",
                    json={"lines": [{"line_id": 1, "received_qty": 1}]},
                    headers=_h(key))
    assert r.status_code == 409


def test_receive_missing_lines_returns_400(api_client, sent_po):
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={}, headers=_h(key))
    assert r.status_code == 400


def test_receive_empty_lines_returns_400(api_client, sent_po):
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": []}, headers=_h(key))
    assert r.status_code == 400


def test_receive_unknown_line_id_returns_400(api_client, sent_po):
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": 999999, "received_qty": 5}]},
                    headers=_h(key))
    assert r.status_code == 400


def test_receive_duplicate_line_id_returns_400(api_client, sent_po):
    line_id = sent_po["line"]["id"]
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": line_id, "received_qty": 5},
                                    {"line_id": line_id, "received_qty": 2}]},
                    headers=_h(key))
    assert r.status_code == 400
    assert r.get_json()["error"] == "BAD_REQUEST"


def test_receive_negative_qty_returns_400(api_client, sent_po):
    line_id = sent_po["line"]["id"]
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": line_id, "received_qty": -1}]},
                    headers=_h(key))
    assert r.status_code == 400


def test_receive_non_numeric_qty_returns_400(api_client, sent_po):
    line_id = sent_po["line"]["id"]
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": line_id, "received_qty": "lots"}]},
                    headers=_h(key))
    assert r.status_code == 400


def test_receive_all_zero_qty_returns_400(api_client, sent_po):
    line_id = sent_po["line"]["id"]
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": line_id, "received_qty": 0}]},
                    headers=_h(key))
    assert r.status_code == 400
    assert r.get_json()["error"] == "BAD_REQUEST"


def test_receive_full_receipt_sets_status_received(api_client, sent_po):
    line_id = sent_po["line"]["id"]
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": line_id, "received_qty": 10}]},
                    headers=_h(key))
    assert r.status_code == 200
    assert r.get_json()["status"] == "RECEIVED"


def test_receive_partial_receipt_sets_status_partial(api_client, sent_po_two_lines):
    first_line_id = sent_po_two_lines["lines"][0]["id"]
    client, key = api_client
    r = client.post(
        f"/api/v1/purchase-orders/{sent_po_two_lines['po_id']}/receive",
        json={"lines": [{"line_id": first_line_id, "received_qty": 5}]},
        headers=_h(key),
    )
    assert r.status_code == 200
    assert r.get_json()["status"] == "PARTIAL"


def test_receive_updates_stock_on_hand(api_client, sent_po, product_barcode):
    """10 cartons × pack_qty 6 = 60 units added to SOH."""
    line_id = sent_po["line"]["id"]
    client, key = api_client
    client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                json={"lines": [{"line_id": line_id, "received_qty": 10}]},
                headers=_h(key))
    soh = soh_model.get_by_barcode(product_barcode)
    assert soh["quantity"] == 60


def test_receive_response_includes_lines_received_count(api_client, sent_po):
    line_id = sent_po["line"]["id"]
    client, key = api_client
    data = client.post(
        f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
        json={"lines": [{"line_id": line_id, "received_qty": 10}]},
        headers=_h(key),
    ).get_json()
    assert data["lines_received"] == 1


def test_receive_stores_invoice_number(api_client, sent_po, test_db):
    line_id = sent_po["line"]["id"]
    client, key = api_client
    client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                json={"lines": [{"line_id": line_id, "received_qty": 10}],
                      "invoice_number": "INV-999"},
                headers=_h(key))
    po = po_ctrl.get_po_by_id(sent_po["po_id"])
    assert po["supplier_invoice_number"] == "INV-999"


def test_receive_completing_partial_po_sets_received(api_client, sent_po_two_lines):
    """Receive first line on one call (PARTIAL), then second line — should become RECEIVED."""
    lines = sent_po_two_lines["lines"]
    po_id = sent_po_two_lines["po_id"]
    client, key = api_client

    # First call: receive only line 1 → PARTIAL
    r1 = client.post(f"/api/v1/purchase-orders/{po_id}/receive",
                     json={"lines": [{"line_id": lines[0]["id"], "received_qty": 10}]},
                     headers=_h(key))
    assert r1.get_json()["status"] == "PARTIAL"

    # Second call: receive line 2 → RECEIVED
    r2 = client.post(f"/api/v1/purchase-orders/{po_id}/receive",
                     json={"lines": [{"line_id": lines[1]["id"], "received_qty": 5}]},
                     headers=_h(key))
    assert r2.status_code == 200
    assert r2.get_json()["status"] == "RECEIVED"


def test_receive_requires_auth(api_client, sent_po):
    client, _ = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": sent_po['line']['id'], "received_qty": 1}]})
    assert r.status_code == 401


def test_receive_po_with_only_note_lines_returns_400(api_client, test_db, supplier_id):
    """A SENT PO whose only line is a note (no product lines) has nothing
    to receive against — all_lines is empty after filtering out notes."""
    po_id = po_ctrl.create_po(supplier_id)
    po_ctrl.update_po_status(po_id, "SENT")
    lines_model.add_note(po_id, "Note only, no products")
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{po_id}/receive",
                    json={"lines": [{"line_id": 1, "received_qty": 1}]},
                    headers=_h(key))
    assert r.status_code == 400
    assert r.get_json()["error"] == "BAD_REQUEST"


def test_receive_non_integer_line_id_returns_400(api_client, sent_po):
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": "abc", "received_qty": 5}]},
                    headers=_h(key))
    assert r.status_code == 400
    assert r.get_json()["error"] == "BAD_REQUEST"


def test_receive_atomic_failure_returns_500(api_client, sent_po, monkeypatch):
    monkeypatch.setattr(
        po_ctrl, "receive_po_atomic",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db exploded")),
    )
    line_id = sent_po["line"]["id"]
    client, key = api_client
    r = client.post(f"/api/v1/purchase-orders/{sent_po['po_id']}/receive",
                    json={"lines": [{"line_id": line_id, "received_qty": 10}]},
                    headers=_h(key))
    assert r.status_code == 500
    assert r.get_json()["error"] == "RECEIVE_FAILED"
