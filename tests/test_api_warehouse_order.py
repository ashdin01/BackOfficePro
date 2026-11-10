"""Warehouse Order: flag, items endpoint, submit writes CSV + PDF (no DB record)."""
import csv
import os
import pytest
import controllers.product_controller as product_ctrl
import controllers.settings_controller as settings_ctrl


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


@pytest.fixture()
def out_dir(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    settings_ctrl.set_setting("warehouse_order_output_dir", str(d))
    return d


def _h(key):
    return {"X-API-Key": key}


def test_items_empty_until_flagged(api_client, product_barcode):
    client, key = api_client
    assert client.get("/api/v1/warehouse-order/items", headers=_h(key)).get_json() == []
    product_ctrl.set_warehouse_order_include(product_barcode, True)
    items = client.get("/api/v1/warehouse-order/items", headers=_h(key)).get_json()
    assert [i["barcode"] for i in items] == [product_barcode]


def test_submit_writes_csv_and_pdf_merging_rescans(api_client, product_barcode, out_dir):
    client, key = api_client
    product_ctrl.set_warehouse_order_include(product_barcode, True)
    r = client.post("/api/v1/warehouse-order/submit", headers=_h(key), json={
        "lines": [{"barcode": product_barcode, "qty": 2}, {"barcode": product_barcode, "qty": 3}]})
    assert r.status_code == 201
    body = r.get_json()
    assert body["line_count"] == 1 and body["total_units"] == 5
    rows = list(csv.reader(open(out_dir / body["csv"], encoding="utf-8-sig")))
    assert rows[0] == ["Barcode", "Product Description", "Order Qty"]
    assert rows[1][0] == product_barcode and rows[1][2] == "5"
    assert (out_dir / body["pdf"]).read_bytes().startswith(b"%PDF")


def test_same_minute_resend_does_not_overwrite(api_client, product_barcode, out_dir):
    client, key = api_client
    product_ctrl.set_warehouse_order_include(product_barcode, True)
    payload = {"lines": [{"barcode": product_barcode, "qty": 1}]}
    a = client.post("/api/v1/warehouse-order/submit", headers=_h(key), json=payload).get_json()
    b = client.post("/api/v1/warehouse-order/submit", headers=_h(key), json=payload).get_json()
    assert a["csv"] != b["csv"] and len(os.listdir(out_dir)) == 4


@pytest.mark.parametrize("lines", [
    [], None, [{"barcode": "123"}], [{"barcode": "NOPE", "qty": 1}], "x",
])
def test_submit_rejects_bad_input(api_client, product_barcode, out_dir, lines):
    client, key = api_client
    product_ctrl.set_warehouse_order_include(product_barcode, True)
    r = client.post("/api/v1/warehouse-order/submit", headers=_h(key), json={"lines": lines})
    assert r.status_code == 400 and os.listdir(out_dir) == []


@pytest.mark.parametrize("qty", [0, -1, "abc", 100000])
def test_submit_rejects_bad_qty(api_client, product_barcode, out_dir, qty):
    client, key = api_client
    product_ctrl.set_warehouse_order_include(product_barcode, True)
    r = client.post("/api/v1/warehouse-order/submit", headers=_h(key),
                    json={"lines": [{"barcode": product_barcode, "qty": qty}]})
    assert r.status_code == 400


def test_unflagged_product_rejected(api_client, product_barcode, out_dir):
    client, key = api_client
    r = client.post("/api/v1/warehouse-order/submit", headers=_h(key),
                    json={"lines": [{"barcode": product_barcode, "qty": 1}]})
    assert r.status_code == 400


def test_unwritable_output_dir_returns_500(api_client, product_barcode, tmp_path):
    client, key = api_client
    blocker = tmp_path / "file"; blocker.write_text("x")
    settings_ctrl.set_setting("warehouse_order_output_dir", str(blocker / "sub"))
    product_ctrl.set_warehouse_order_include(product_barcode, True)
    r = client.post("/api/v1/warehouse-order/submit", headers=_h(key),
                    json={"lines": [{"barcode": product_barcode, "qty": 1}]})
    assert r.status_code == 500
