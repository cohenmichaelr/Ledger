"""LED-303/304: GET /portfolios/{id}/value with fake prices. Nothing here calls Tiingo.

The real price provider is swapped out with app.dependency_overrides (C# analogy: replacing a
service registration in WebApplicationFactory.ConfigureTestServices).

Hand check for samples/trades.csv at the fake prices below (AAPL 200.00, NVDA 120.50):

  AAPL  buy 10 @ 180, buy 10 @ 190, sell 5 (FIFO: from the 180 lot)
        open lots 5 @ 180 + 10 @ 190 -> qty 15, cost 900 + 1900 = 2800, avg 186.666667
        value 15 x 200.00 = 3000.00, unrealized 3000 - 2800 = 200.00
  MSFT  buy 5, sell 5 -> closed, not listed
  NVDA  buy 20 @ 110.25 -> cost 2205.00, value 20 x 120.50 = 2410.00, unrealized 205.00
  Total value 5410.00, cost 5005.00, unrealized 405.00
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ledger.db import SessionDep
from ledger.market_data import MarketDataError, PriceQuote
from ledger.price_cache import CachedPriceProvider, get_price_provider
from ledger.valuation import value_holdings

SAMPLE_CSV = Path(__file__).parent.parent / "samples" / "trades.csv"
FRIDAY = date(2026, 10, 23)


class FakePrices:
    """A price provider with fixed closes. `down=True` makes every call fail like an outage."""

    def __init__(self, closes: dict[str, str]):
        self.closes = {s: Decimal(c) for s, c in closes.items()}
        self.calls: list[str] = []
        self.down = False

    def latest_close(self, symbol: str) -> PriceQuote:
        self.calls.append(symbol)
        if self.down:
            raise MarketDataError(f"Could not reach the price provider for {symbol}.")
        if symbol not in self.closes:
            raise MarketDataError(f"Unknown symbol: {symbol}.")
        return PriceQuote(symbol=symbol, close=self.closes[symbol], as_of=FRIDAY)


@pytest.fixture
def prices(client) -> FakePrices:
    fake = FakePrices({"AAPL": "200.00", "NVDA": "120.50", "MSFT": "410.00"})
    client.app.dependency_overrides[get_price_provider] = lambda: fake
    return fake


def new_portfolio(client, name: str = "Main") -> int:
    return client.post("/portfolios", json={"name": name}).json()["id"]


def upload_sample(client, portfolio_id: int) -> None:
    with SAMPLE_CSV.open("rb") as f:
        r = client.post(f"/portfolios/{portfolio_id}/trades", files={"file": f})
    assert r.status_code == 201, r.text


def test_sample_portfolio_value_matches_hand_check(client, prices):
    pid = new_portfolio(client)
    upload_sample(client, pid)

    r = client.get(f"/portfolios/{pid}/value")

    assert r.status_code == 200
    body = r.json()
    by_symbol = {p["symbol"]: p for p in body["positions"]}
    assert list(by_symbol) == ["AAPL", "NVDA"]  # MSFT is closed, sorted by symbol

    aapl = by_symbol["AAPL"]
    assert Decimal(aapl["quantity"]) == 15
    assert Decimal(aapl["avg_cost"]) == Decimal("186.666667")
    assert Decimal(aapl["cost_basis"]) == 2800  # exact lot cost, not 15 x 186.666667
    assert aapl["price"] == "200.000000"  # same format whether fresh or cached
    assert Decimal(aapl["market_value"]) == 3000
    assert Decimal(aapl["unrealized_pnl"]) == 200

    nvda = by_symbol["NVDA"]
    assert Decimal(nvda["cost_basis"]) == Decimal("2205.00")
    assert Decimal(nvda["market_value"]) == Decimal("2410.00")
    assert Decimal(nvda["unrealized_pnl"]) == Decimal("205.00")

    assert Decimal(body["total_market_value"]) == Decimal("5410.00")
    assert Decimal(body["total_cost_basis"]) == Decimal("5005.00")
    assert Decimal(body["total_unrealized_pnl"]) == Decimal("405.00")
    assert prices.calls == ["AAPL", "NVDA"]  # no price fetched for the closed MSFT position


def test_each_price_shows_its_as_of_date(client, prices):
    pid = new_portfolio(client)
    upload_sample(client, pid)

    for position in client.get(f"/portfolios/{pid}/value").json()["positions"]:
        assert position["price_as_of"] == "2026-10-23"
        assert position["price_stale"] is False


def test_losing_position_has_negative_unrealized_pnl(client, prices):
    pid = new_portfolio(client)
    client.post(
        f"/portfolios/{pid}/trades",
        json={"symbol": "MSFT", "side": "BUY", "quantity": "2", "price": "450.25",
              "executed_at": "2026-10-01T15:00:00Z"},
    )  # fmt: skip

    body = client.get(f"/portfolios/{pid}/value").json()
    # 2 x 410.00 - 2 x 450.25 = 820.00 - 900.50
    assert Decimal(body["total_unrealized_pnl"]) == Decimal("-80.50")


def test_empty_portfolio_is_zero_and_fetches_no_prices(client, prices):
    pid = new_portfolio(client)

    body = client.get(f"/portfolios/{pid}/value").json()

    assert body["positions"] == []
    assert Decimal(body["total_market_value"]) == 0
    assert Decimal(body["total_unrealized_pnl"]) == 0
    assert prices.calls == []


def test_unknown_portfolio_is_404(client, prices):
    assert client.get("/portfolios/999/value").status_code == 404


def test_symbol_with_no_price_at_all_is_503_naming_it(client, prices):
    pid = new_portfolio(client)
    upload_sample(client, pid)
    prices.down = True  # no cache in front of the fake here, so nothing to fall back on

    r = client.get(f"/portfolios/{pid}/value")

    assert r.status_code == 503
    assert r.json() == {"detail": "Could not reach the price provider for AAPL."}


def test_api_down_uses_cached_prices(client):
    """LED-302's last criterion, end to end: the real cache in front of a fake provider."""
    fake = FakePrices({"AAPL": "200.00", "NVDA": "120.50"})
    clock = {"now": datetime(2026, 10, 26, 15, 0, tzinfo=UTC)}  # Monday in New York

    def cached_fake(session: SessionDep):
        # Same signature style as the real dependency, so the test session is injected
        return CachedPriceProvider(fake, session, now=lambda: clock["now"])

    client.app.dependency_overrides[get_price_provider] = cached_fake
    pid = new_portfolio(client)
    upload_sample(client, pid)
    assert client.get(f"/portfolios/{pid}/value").status_code == 200  # fills the cache

    fake.down = True
    clock["now"] = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)  # next day: the cache will retry
    r = client.get(f"/portfolios/{pid}/value")

    assert r.status_code == 200
    body = r.json()
    assert fake.calls == ["AAPL", "NVDA", "AAPL", "NVDA"]  # it did try the API again
    assert all(p["price_stale"] for p in body["positions"])
    assert body["positions"][0]["price"] == "200.000000"
    assert Decimal(body["total_market_value"]) == Decimal("5410.00")  # yesterday's prices


def test_value_holdings_totals_are_sums_of_rounded_parts():
    """Pure-function check: odd decimals round per symbol, and totals add up exactly."""
    holdings = {
        "AAA": (Decimal("3"), Decimal("10")),  # avg 3.333333...
        "BBB": (Decimal("0.5"), Decimal("1.0000001")),
    }
    quotes = {
        "AAA": PriceQuote("AAA", Decimal("3.3333337"), FRIDAY),
        "BBB": PriceQuote("BBB", Decimal("2.0000003"), FRIDAY),
    }

    value = value_holdings(1, holdings, quotes)

    aaa, bbb = value.positions
    assert aaa.avg_cost == Decimal("3.333333")
    assert aaa.market_value == Decimal("10.000001")  # 10.0000011 rounded to 6 places
    assert bbb.cost_basis == Decimal("1.000000")
    assert value.total_market_value == aaa.market_value + bbb.market_value
    assert value.total_unrealized_pnl == aaa.unrealized_pnl + bbb.unrealized_pnl
