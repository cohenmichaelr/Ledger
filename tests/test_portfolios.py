"""Portfolio endpoints: create/list portfolios, add trades (JSON or CSV), list trades."""

from decimal import Decimal

import pytest

TRADE = {
    "symbol": "aapl",
    "side": "BUY",
    "quantity": "10",
    "price": "187.50",
    "executed_at": "2026-09-24T14:30:00Z",
}
HEADER = "date,symbol,side,quantity,price\n"


def create_portfolio(client, name="Retirement") -> int:
    r = client.post("/portfolios", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


def upload(client, portfolio_id, csv: str):
    return client.post(
        f"/portfolios/{portfolio_id}/trades",
        files={"file": ("trades.csv", csv, "text/csv")},
    )


# --- POST /portfolios, GET /portfolios ---------------------------------------------------------


def test_create_portfolio_returns_201_with_id(client):
    r = client.post("/portfolios", json={"name": "  Retirement  "})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert body["name"] == "Retirement"  # surrounding whitespace trimmed
    assert body["created_at"]


def test_duplicate_portfolio_name_returns_409(client):
    create_portfolio(client, "Retirement")
    r = client.post("/portfolios", json={"name": "Retirement"})
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 65])
def test_invalid_portfolio_name_returns_422(client, name):
    assert client.post("/portfolios", json={"name": name}).status_code == 422


def test_list_portfolios(client):
    a = create_portfolio(client, "A")
    b = create_portfolio(client, "B")
    r = client.get("/portfolios")
    assert r.status_code == 200
    assert [(p["id"], p["name"]) for p in r.json()] == [(a, "A"), (b, "B")]


# --- POST /portfolios/{id}/trades ----------------------------------------------------------------


def test_add_single_trade_as_json(client):
    pid = create_portfolio(client)
    r = client.post(f"/portfolios/{pid}/trades", json=TRADE)
    assert r.status_code == 201
    body = r.json()
    assert body["portfolio_id"] == pid
    assert body["symbol"] == "AAPL"
    assert body["id"] > 0


def test_invalid_json_trade_returns_422(client):
    pid = create_portfolio(client)
    r = client.post(f"/portfolios/{pid}/trades", json={**TRADE, "quantity": "0"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "quantity"]


def test_add_trades_as_csv_returns_created_trades(client):
    pid = create_portfolio(client)
    r = upload(client, pid, HEADER + "2026-09-01,AAPL,BUY,10,180\n2026-09-02,MSFT,BUY,5,400\n")
    assert r.status_code == 201
    trades = r.json()
    assert [t["symbol"] for t in trades] == ["AAPL", "MSFT"]  # file order
    assert {t["portfolio_id"] for t in trades} == {pid}
    assert all(t["id"] > 0 for t in trades)


def test_bad_csv_row_returns_422_and_stores_nothing(client):
    pid = create_portfolio(client)
    r = upload(client, pid, HEADER + "2026-09-01,AAPL,BUY,10,180\n2026-09-02,AAPL,BUY,-1,180\n")
    assert r.status_code == 422
    assert r.json()["detail"][0]["row"] == 3
    assert client.get(f"/portfolios/{pid}/trades").json() == []


def test_multipart_without_file_field_returns_422(client):
    pid = create_portfolio(client)
    r = client.post(f"/portfolios/{pid}/trades", data={"not_file": "x"}, files={"x": ("a", "b")})
    assert r.status_code == 422
    assert "'file' field" in r.json()["detail"][0]["reason"]


def test_unsupported_content_type_returns_415(client):
    pid = create_portfolio(client)
    r = client.post(
        f"/portfolios/{pid}/trades", content="hello", headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 415


def test_oversell_single_trade_returns_422_and_stores_nothing(client):
    pid = create_portfolio(client)
    client.post(f"/portfolios/{pid}/trades", json=TRADE)  # hold 10 AAPL
    r = client.post(f"/portfolios/{pid}/trades", json={**TRADE, "side": "SELL", "quantity": "11"})
    assert r.status_code == 422
    assert r.json()["detail"] == [{"row": None, "reason": "SELL 11 AAPL exceeds position of 10"}]
    assert len(client.get(f"/portfolios/{pid}/trades").json()) == 1


def test_oversell_is_checked_per_portfolio(client):
    rich = create_portfolio(client, "Rich")
    empty = create_portfolio(client, "Empty")
    client.post(f"/portfolios/{rich}/trades", json=TRADE)  # AAPL is held in "Rich" only
    sell = {**TRADE, "side": "SELL", "quantity": "5"}
    assert client.post(f"/portfolios/{empty}/trades", json=sell).status_code == 422
    assert client.post(f"/portfolios/{rich}/trades", json=sell).status_code == 201


# --- GET /portfolios/{id}/trades -----------------------------------------------------------------


def test_list_trades_newest_first(client):
    pid = create_portfolio(client)
    upload(
        client,
        pid,
        HEADER
        + "2026-09-01,AAPL,BUY,1,100\n"
        + "2026-09-03,NVDA,BUY,1,100\n"
        + "2026-09-02,MSFT,BUY,1,100\n",
    )
    r = client.get(f"/portfolios/{pid}/trades")
    assert r.status_code == 200
    assert [t["symbol"] for t in r.json()] == ["NVDA", "MSFT", "AAPL"]


def test_list_trades_only_returns_that_portfolios_trades(client):
    a = create_portfolio(client, "A")
    b = create_portfolio(client, "B")
    client.post(f"/portfolios/{a}/trades", json=TRADE)
    client.post(f"/portfolios/{b}/trades", json={**TRADE, "symbol": "MSFT"})
    assert [t["symbol"] for t in client.get(f"/portfolios/{a}/trades").json()] == ["AAPL"]


def test_trade_values_round_trip(client):
    pid = create_portfolio(client)
    client.post(f"/portfolios/{pid}/trades", json=TRADE)
    [t] = client.get(f"/portfolios/{pid}/trades").json()
    assert Decimal(t["quantity"]) == 10
    assert Decimal(t["price"]) == Decimal("187.50")


# --- Unknown portfolio ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("get", {}),
        ("post", {"json": TRADE}),
        ("post", {"json": {"garbage": True}}),  # 404 wins over an invalid body
        ("post", {"files": {"file": ("t.csv", "not,a,valid,header\n", "text/csv")}}),
    ],
    ids=["list", "add-json", "add-invalid-body", "add-csv"],
)
def test_unknown_portfolio_returns_404(client, method, kwargs):
    r = getattr(client, method)("/portfolios/9999/trades", **kwargs)
    assert r.status_code == 404
    assert r.json()["detail"] == "Portfolio not found"
