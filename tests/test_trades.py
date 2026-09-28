"""Week 1 spec for the trades API.

Run just these:  uv run pytest tests/test_trades.py -v
"""

from decimal import Decimal
from pathlib import Path

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


# --- CSV import -------------------------------------------------------------------------------

SAMPLE_CSV = Path(__file__).parent.parent / "samples" / "trades.csv"


def upload(client, content: str | bytes):
    # files= sends multipart/form-data: field name -> (filename, content, content type)
    return client.post("/trades/import", files={"file": ("trades.csv", content, "text/csv")})


def test_import_sample_csv_returns_positions(client):
    r = upload(client, SAMPLE_CSV.read_bytes())
    assert r.status_code == 200
    positions = {p["symbol"]: p for p in r.json()}
    # MSFT was bought and fully sold, so it's excluded
    assert sorted(positions) == ["AAPL", "NVDA"]
    # AAPL: sold 5 of the first lot (10 @ 180) -> 5 @ 180 + 10 @ 190 = 2800 / 15
    assert Decimal(positions["AAPL"]["quantity"]) == 15
    assert Decimal(positions["AAPL"]["avg_cost"]) == Decimal("186.666667")
    assert Decimal(positions["NVDA"]["quantity"]) == 20
    assert Decimal(positions["NVDA"]["avg_cost"]) == Decimal("110.25")


def test_import_stores_trades(client):
    upload(client, SAMPLE_CSV.read_bytes())
    assert len(client.get("/trades").json()) == 6


def test_import_positions_include_previously_stored_trades(client):
    client.post("/trades", json={**TRADE, "quantity": "10", "price": "100"})
    r = upload(client, "date,symbol,side,quantity,price\n2026-09-25,AAPL,BUY,10,200\n")
    assert r.status_code == 200
    [aapl] = r.json()
    assert Decimal(aapl["quantity"]) == 20
    assert Decimal(aapl["avg_cost"]) == 150


def test_import_malformed_row_returns_422_with_row_number(client):
    csv = (
        "date,symbol,side,quantity,price\n2026-09-01,AAPL,BUY,10,180\n2026-09-02,AAPL,BUY,-5,180\n"
    )
    r = upload(client, csv)
    assert r.status_code == 422
    [error] = r.json()["detail"]
    assert error["row"] == 3
    assert "quantity" in error["reason"]


def test_import_reports_every_bad_row(client):
    csv = (
        "date,symbol,side,quantity,price\n"
        "not-a-date,AAPL,BUY,10,180\n"
        "2026-09-02,AAPL,HOLD,10,180\n"
        "2026-09-03,AAPL,BUY,10\n"
    )
    r = upload(client, csv)
    assert r.status_code == 422
    errors = r.json()["detail"]
    assert [e["row"] for e in errors] == [2, 3, 4]
    assert errors[0]["reason"].startswith("date:")
    assert errors[1]["reason"].startswith("side:")
    assert "columns" in errors[2]["reason"]


def test_import_bad_header_returns_422_on_row_1(client):
    r = upload(client, "when,ticker,side,qty,px\n2026-09-01,AAPL,BUY,10,180\n")
    assert r.status_code == 422
    assert r.json()["detail"][0]["row"] == 1


def test_import_oversell_returns_422_with_row_number(client):
    csv = (
        "date,symbol,side,quantity,price\n2026-09-01,AAPL,BUY,10,180\n2026-09-02,AAPL,SELL,11,190\n"
    )
    r = upload(client, csv)
    assert r.status_code == 422
    [error] = r.json()["detail"]
    assert error["row"] == 3
    assert "exceeds position" in error["reason"]


def test_failed_import_stores_nothing(client):
    csv = (
        "date,symbol,side,quantity,price\n2026-09-01,AAPL,BUY,10,180\n2026-09-02,AAPL,SELL,11,190\n"
    )
    upload(client, csv)
    assert client.get("/trades").json() == []
