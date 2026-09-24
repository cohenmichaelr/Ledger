"""Week 1 spec. Remove the skip marker once you've implemented api/trades.py.

Run just these:  uv run pytest tests/test_trades.py -v
"""

import pytest

pytestmark = pytest.mark.skip(reason="Week 1: implement api/trades.py, then delete this line")

TRADE = {
    "symbol": "aapl",
    "side": "BUY",
    "quantity": "10",
    "price": "187.50",
    "executed_at": "2026-09-24T14:30:00Z",
}


def test_create_trade_returns_201_and_uppercases_symbol(client):
    r = client.post("/trades", json=TRADE)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert body["symbol"] == "AAPL"


def test_create_trade_rejects_nonpositive_quantity(client):
    r = client.post("/trades", json={**TRADE, "quantity": "0"})
    assert r.status_code == 422


def test_get_trade_by_id(client):
    created = client.post("/trades", json=TRADE).json()
    r = client.get(f"/trades/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_missing_trade_returns_404(client):
    assert client.get("/trades/9999").status_code == 404


def test_list_trades_filters_by_symbol(client):
    client.post("/trades", json=TRADE)
    client.post("/trades", json={**TRADE, "symbol": "MSFT"})
    r = client.get("/trades", params={"symbol": "MSFT"})
    assert r.status_code == 200
    assert [t["symbol"] for t in r.json()] == ["MSFT"]
