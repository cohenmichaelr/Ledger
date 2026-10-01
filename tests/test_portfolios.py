"""Portfolio endpoints: create/list portfolios, add trades (JSON or CSV), list trades, P&L."""

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


# --- GET /portfolios/{id}/pnl --------------------------------------------------------------------


def test_realized_pnl_per_symbol_and_total(client):
    pid = create_portfolio(client)
    upload(
        client,
        pid,
        HEADER
        + "2026-09-01,AAPL,BUY,10,100\n"
        + "2026-09-02,AAPL,BUY,10,110\n"
        + "2026-09-03,MSFT,BUY,5,400\n"
        + "2026-09-04,AAPL,SELL,15,120\n"  # FIFO: 10 x 20 + 5 x 10 = 250
        + "2026-09-05,MSFT,SELL,5,380\n"  # 5 x -20 = -100
        + "2026-09-06,NVDA,BUY,1,100\n",  # never sold, so not listed
    )
    r = client.get(f"/portfolios/{pid}/pnl")
    assert r.status_code == 200
    body = r.json()
    assert body["portfolio_id"] == pid
    assert [(s["symbol"], Decimal(s["realized_pnl"])) for s in body["symbols"]] == [
        ("AAPL", Decimal("250")),
        ("MSFT", Decimal("-100")),
    ]
    assert Decimal(body["total"]) == Decimal("150")


def test_realized_pnl_uses_execution_order_not_upload_order(client):
    pid = create_portfolio(client)
    upload(client, pid, HEADER + "2026-09-02,AAPL,BUY,10,110\n")
    upload(client, pid, HEADER + "2026-09-01,AAPL,BUY,10,100\n")  # older lot, added later
    upload(client, pid, HEADER + "2026-09-03,AAPL,SELL,10,120\n")
    # the 100 lot was bought first, so it is sold first: 10 x (120 - 100)
    assert Decimal(client.get(f"/portfolios/{pid}/pnl").json()["total"]) == Decimal("200")


def test_realized_pnl_empty_portfolio(client):
    pid = create_portfolio(client)
    body = client.get(f"/portfolios/{pid}/pnl").json()
    assert body["symbols"] == []
    assert Decimal(body["total"]) == 0


def test_realized_pnl_only_counts_that_portfolios_trades(client):
    a = create_portfolio(client, "A")
    b = create_portfolio(client, "B")
    for pid in (a, b):
        client.post(f"/portfolios/{pid}/trades", json=TRADE)  # 10 @ 187.50
    client.post(f"/portfolios/{a}/trades", json={**TRADE, "side": "SELL", "price": "200"})
    assert Decimal(client.get(f"/portfolios/{a}/pnl").json()["total"]) == Decimal("125")
    assert client.get(f"/portfolios/{b}/pnl").json()["symbols"] == []


def test_oversell_returns_422_and_leaves_pnl_unchanged(client):
    pid = create_portfolio(client)
    client.post(f"/portfolios/{pid}/trades", json=TRADE)  # hold 10 AAPL
    before = client.get(f"/portfolios/{pid}/pnl").json()
    r = client.post(f"/portfolios/{pid}/trades", json={**TRADE, "side": "SELL", "quantity": "11"})
    assert r.status_code == 422
    assert client.get(f"/portfolios/{pid}/pnl").json() == before


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


def test_pnl_for_unknown_portfolio_returns_404(client):
    r = client.get("/portfolios/9999/pnl")
    assert r.status_code == 404
    assert r.json()["detail"] == "Portfolio not found"
