# -*- coding: utf-8 -*-
"""Bulk summary для экрана People: один запрос вместо N*2 (card + stage на клиента).

GET /api/crm/clients/summary?ids=1,2,3 -> {"clients": {"1": {"stage","next_step","card"}}}
"""
from __future__ import annotations


def _mk(c, name):
    r = c.post("/api/orders/clients", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_summary_returns_all_three(_client):
    c = _client
    ids = [_mk(c, f"Балк-{i}") for i in range(3)]
    # next_step одному — проверить проброс
    c.put(f"/api/crm/clients/{ids[0]}", json={"next_step": "позвонить"})
    r = c.get("/api/crm/clients/summary", params={"ids": ",".join(map(str, ids))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["clients"].keys()) == {str(i) for i in ids}
    for cid in ids:
        entry = body["clients"][str(cid)]
        assert "stage" in entry and "card" in entry and "next_step" in entry
        # card — то же, что отдельный card-эндпоинт
        solo = c.get(f"/api/crm/clients/{cid}/card")
        assert solo.status_code == 200
        assert entry["card"] == solo.json()
        # stage — то же, что отдельный stage-эндпоинт
        st = c.get(f"/api/crm/clients/{cid}/stage")
        assert st.status_code == 200
        assert entry["stage"] == st.json()["stage"]
    assert body["clients"][str(ids[0])]["next_step"] == "позвонить"


def test_summary_skips_unknown(_client):
    c = _client
    cid = _mk(c, "Балк-живой")
    r = c.get("/api/crm/clients/summary", params={"ids": f"{cid},999999"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert str(cid) in body["clients"]
    assert "999999" not in body["clients"]


def test_summary_empty_ids(_client):
    c = _client
    r = c.get("/api/crm/clients/summary")
    assert r.status_code == 200, r.text
    assert r.json() == {"clients": {}}
    r2 = c.get("/api/crm/clients/summary", params={"ids": ""})
    assert r2.status_code == 200
    assert r2.json() == {"clients": {}}


def test_summary_next_step_present(_client):
    c = _client
    cid = _mk(c, "Балк-шаг")
    c.put(f"/api/crm/clients/{cid}", json={"next_step": "написать"})
    r = c.get("/api/crm/clients/summary", params={"ids": str(cid)})
    assert r.status_code == 200, r.text
    assert r.json()["clients"][str(cid)]["next_step"] == "написать"
