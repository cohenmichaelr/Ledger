"""LED-301: the Tiingo adapter. These tests never touch the network.

httpx.MockTransport answers requests with a function we write, so each test decides exactly
what "Tiingo" sends back (C# analogy: a fake HttpMessageHandler passed to HttpClient).
"""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from ledger.market_data import MarketDataError, PriceQuote, TiingoProvider

AAPL_DAY = [
    {
        "date": "2026-10-23T00:00:00.000Z",
        "open": 230.1,
        "high": 233.0,
        "low": 229.5,
        "close": 231.47,
        "volume": 41234567,
        "adjClose": 231.47,
    }
]


def provider_returning(handler) -> TiingoProvider:
    return TiingoProvider("test-key", transport=httpx.MockTransport(handler))


def respond(status: int, body=None):
    """Handler that ignores the request and returns a fixed response."""
    return lambda request: httpx.Response(status, json=body)


def test_parses_latest_close_as_decimal_with_its_date():
    quote = provider_returning(respond(200, AAPL_DAY)).latest_close("aapl")
    assert quote == PriceQuote(symbol="AAPL", close=Decimal("231.47"), as_of=date(2026, 10, 23))
    assert isinstance(quote.close, Decimal)


def test_uses_the_last_row_when_several_days_come_back():
    two_days = [{"date": "2026-10-22T00:00:00.000Z", "close": 228.0}, AAPL_DAY[0]]
    assert provider_returning(respond(200, two_days)).latest_close("AAPL").as_of == date(
        2026, 10, 23
    )


def test_sends_key_in_auth_header_and_symbol_in_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["path"] = request.url.path
        return httpx.Response(200, json=AAPL_DAY)

    provider_returning(handler).latest_close(" brk-b ")
    assert seen == {"auth": "Token test-key", "path": "/tiingo/daily/BRK-B/prices"}


def test_missing_api_key_is_a_clear_error():
    with pytest.raises(MarketDataError, match="LEDGER_TIINGO_API_KEY"):
        TiingoProvider(None)
    with pytest.raises(MarketDataError, match="LEDGER_TIINGO_API_KEY"):
        TiingoProvider("")


@pytest.mark.parametrize("bad", ["AAPL/../x", "MS FT", "", "A" * 17])
def test_invalid_symbol_is_rejected_before_any_request(bad):
    def handler(request):
        raise AssertionError("no request should be made")

    with pytest.raises(MarketDataError, match="Invalid symbol"):
        provider_returning(handler).latest_close(bad)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "Unknown symbol: ZZZZ"),
        (401, "rejected the API key"),
        (403, "rejected the API key"),
        (429, "rate limit"),
        (500, r"error \(500\)"),
        (503, r"error \(503\)"),
    ],
)
def test_provider_error_statuses_become_clear_errors(status, message):
    with pytest.raises(MarketDataError, match=message):
        provider_returning(respond(status, {"detail": "nope"})).latest_close("ZZZZ")


def test_timeout_is_a_clear_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(MarketDataError, match="timed out"):
        provider_returning(handler).latest_close("AAPL")


def test_connection_failure_is_a_clear_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(MarketDataError, match="Could not reach"):
        provider_returning(handler).latest_close("AAPL")


@pytest.mark.parametrize("body", [[], {"detail": "weird"}, [{"date": "2026-10-23"}], "oops"])
def test_unexpected_response_shape_is_a_clear_error(body):
    with pytest.raises(MarketDataError, match="Unexpected response"):
        provider_returning(respond(200, body)).latest_close("AAPL")
