"""Price cache: wraps any PriceProvider and stores its prices in the database (LED-302).

C# analogy: a caching decorator around IPriceProvider. It implements the same interface, so
callers can't tell whether a price came from the API or the database.

Rules:
- Each symbol is fetched at most once per New York calendar day. Weekends and holidays count
  as days too (no market calendar in v1), so they cost at most one fetch each.
- If the provider fails, the last cached price is returned with `stale=True`.
- If the provider fails and nothing is cached, the MarketDataError propagates.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo  # standard-library time zones (needs the tzdata package on Windows)

from sqlalchemy.orm import Session

from ledger.config import get_settings
from ledger.db import SessionDep
from ledger.market_data import MarketDataError, PriceProvider, PriceQuote, TiingoProvider
from ledger.models import Price

MARKET_TZ = ZoneInfo("America/New_York")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CachedPriceProvider:
    def __init__(
        self,
        provider: PriceProvider,
        session: Session,
        *,
        # Injected so tests can control the date (like injecting TimeProvider in .NET 8)
        now: Callable[[], datetime] = _utc_now,
    ):
        self._provider = provider
        self._session = session
        self._now = now

    def _trading_day(self) -> date:
        return self._now().astimezone(MARKET_TZ).date()

    def latest_close(self, symbol: str) -> PriceQuote:
        symbol = symbol.strip().upper()
        cached = self._session.get(Price, symbol)  # primary-key lookup, like EF's Find()
        today = self._trading_day()

        if cached is not None and cached.fetched_on == today:
            return _quote(cached)

        try:
            quote = self._provider.latest_close(symbol)
        except MarketDataError:
            if cached is None:
                raise  # bare `raise` re-throws the current exception, like `throw;` in C#
            return _quote(cached, stale=True)

        if cached is None:
            cached = Price(symbol=quote.symbol)
            self._session.add(cached)
        cached.close, cached.as_of = quote.close, quote.as_of
        cached.fetched_on, cached.fetched_at = today, self._now()
        # Commit now so the price is kept even if the rest of the request fails.
        self._session.commit()
        return quote


def _quote(row: Price, *, stale: bool = False) -> PriceQuote:
    return PriceQuote(symbol=row.symbol, close=row.close, as_of=row.as_of, stale=stale)


def get_price_provider(session: SessionDep) -> Iterator[PriceProvider]:
    """FastAPI dependency for the valuation endpoint: Tiingo behind the cache.

    A `yield` dependency runs the code after `yield` once the request is done, so the HTTP
    client is closed every time (like a scoped IDisposable). Tests override this with a fake
    (app.dependency_overrides), so they never reach Tiingo.
    """
    tiingo = TiingoProvider(get_settings().tiingo_api_key)
    try:
        yield CachedPriceProvider(tiingo, session)
    finally:
        tiingo.close()
