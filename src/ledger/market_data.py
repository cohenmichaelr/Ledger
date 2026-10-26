"""End-of-day prices from a market data provider (Tiingo today).

The rest of the app depends only on `PriceProvider`, so switching providers means writing one
new class. C# analogy: an `IPriceProvider` interface with a `TiingoPriceProvider` implementation.

Check your API key against the real service:  uv run python -m ledger.market_data AAPL MSFT
"""

import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from ledger.config import get_settings

TIINGO_BASE_URL = "https://api.tiingo.com"
DEFAULT_TIMEOUT_SECONDS = 10.0
# Letters, digits, "." and "-" (Tiingo writes share classes as BRK-B). Anything else could
# change the URL path, so it is rejected before any request is made.
_SYMBOL = re.compile(r"^[A-Z0-9.\-]{1,16}$")


@dataclass(frozen=True)  # frozen = immutable, like a C# record
class PriceQuote:
    symbol: str
    close: Decimal
    as_of: date  # the trading day this closing price is from
    # True when the provider failed and this came from the price cache instead (LED-302)
    stale: bool = False


class MarketDataError(Exception):
    """Any failure getting a price. The message is safe to show to an API user."""


class PriceProvider(Protocol):
    """What the app needs from any price source.

    Protocol = structural interface: any class with a matching `latest_close` method
    satisfies it, without inheriting from it (duck typing, checked by type checkers).
    """

    def latest_close(self, symbol: str) -> PriceQuote: ...


class TiingoProvider:
    """End-of-day closing prices from Tiingo's daily prices endpoint."""

    def __init__(
        self,
        api_key: str | None,
        *,  # everything after * must be passed by name: TiingoProvider(key, timeout=5)
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key:
            raise MarketDataError(
                "No market data API key is configured. Set LEDGER_TIINGO_API_KEY."
            )
        # `transport` lets tests swap in a fake network (like injecting an HttpMessageHandler).
        self._client = httpx.Client(
            base_url=TIINGO_BASE_URL,
            timeout=timeout,
            headers={"Authorization": f"Token {api_key}"},
            transport=transport,
        )

    def latest_close(self, symbol: str) -> PriceQuote:
        symbol = symbol.strip().upper()
        if not _SYMBOL.match(symbol):
            raise MarketDataError(f"Invalid symbol: {symbol!r}.")  # !r = repr(), adds quotes

        try:
            response = self._client.get(f"/tiingo/daily/{symbol}/prices")
        except httpx.TimeoutException as e:
            # `raise ... from e` keeps the original error attached, like an InnerException
            raise MarketDataError(f"The price provider timed out fetching {symbol}.") from e
        except httpx.HTTPError as e:  # DNS failure, connection refused, etc.
            raise MarketDataError(f"Could not reach the price provider for {symbol}.") from e

        if response.status_code == 404:
            raise MarketDataError(f"Unknown symbol: {symbol}.")
        if response.status_code in (401, 403):
            raise MarketDataError(
                "The price provider rejected the API key. Check LEDGER_TIINGO_API_KEY."
            )
        if response.status_code == 429:
            raise MarketDataError("The price provider's rate limit was reached. Try again later.")
        if response.is_error:
            raise MarketDataError(
                f"The price provider returned an error ({response.status_code}) for {symbol}."
            )

        try:
            # parse_float=Decimal reads 187.5 straight into Decimal("187.5"), never a float
            rows = response.json(parse_float=Decimal)
            latest = rows[-1]  # without a date range Tiingo returns the latest trading day
            close = Decimal(latest["close"])
            as_of = date.fromisoformat(latest["date"][:10])  # "2026-10-23T00:00:00.000Z"
        except (ValueError, KeyError, IndexError, TypeError, InvalidOperation) as e:
            raise MarketDataError(
                f"Unexpected response from the price provider for {symbol}."
            ) from e
        return PriceQuote(symbol=symbol, close=close, as_of=as_of)

    def close(self) -> None:
        self._client.close()


if __name__ == "__main__":  # runs only via `python -m ledger.market_data ...`, not on import
    provider = TiingoProvider(get_settings().tiingo_api_key)
    for arg in sys.argv[1:] or ["AAPL"]:
        try:
            q = provider.latest_close(arg)
            print(f"{q.symbol}: {q.close} (close on {q.as_of})")
        except MarketDataError as e:
            print(f"{arg}: {e}")
