"""LED-302: the price cache. A fake provider stands in for Tiingo; nothing touches the network.

The valuation endpoint arrives in LED-303, so these tests drive CachedPriceProvider directly,
which is what that endpoint will call.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ledger.db import Base
from ledger.market_data import MarketDataError, PriceQuote
from ledger.models import Price
from ledger.price_cache import CachedPriceProvider

# 15:00 UTC = 11:00 in New York (EDT); both are Oct 26.
MONDAY_MORNING = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
# 01:00 UTC on Oct 27 is 21:00 Oct 26 in New York: a new UTC day, but the same trading day.
MONDAY_EVENING = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
# 04:30 UTC on Oct 27 = 00:30 Tuesday in New York.
TUESDAY_JUST_AFTER_MIDNIGHT = datetime(2026, 10, 27, 4, 30, tzinfo=UTC)


class FakeProvider:
    """Counts calls; returns a fixed close, or raises when `down` is set."""

    def __init__(self, close: str = "231.47", as_of: date = date(2026, 10, 23)):
        self.close, self.as_of = Decimal(close), as_of
        self.calls: list[str] = []
        self.down = False

    def latest_close(self, symbol: str) -> PriceQuote:
        self.calls.append(symbol)
        if self.down:
            raise MarketDataError("Could not reach the price provider for AAPL.")
        return PriceQuote(symbol=symbol.strip().upper(), close=self.close, as_of=self.as_of)


class Clock:
    """A settable "now" so tests can move between days."""

    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def make_cache(session: Session, provider: FakeProvider, clock: Clock) -> CachedPriceProvider:
    return CachedPriceProvider(provider, session, now=clock)


def test_fetched_price_is_saved_to_the_database(session):
    provider, clock = FakeProvider(), Clock(MONDAY_MORNING)
    quote = make_cache(session, provider, clock).latest_close("AAPL")

    assert quote == PriceQuote(symbol="AAPL", close=Decimal("231.47"), as_of=date(2026, 10, 23))
    row = session.get(Price, "AAPL")
    assert row is not None
    assert (row.close, row.as_of, row.fetched_on) == (
        Decimal("231.47"),
        date(2026, 10, 23),
        date(2026, 10, 26),
    )
    assert isinstance(row.close, Decimal)


def test_same_new_york_day_is_served_from_the_cache(session):
    provider, clock = FakeProvider(), Clock(MONDAY_MORNING)
    cache = make_cache(session, provider, clock)
    cache.latest_close("AAPL")

    clock.now = MONDAY_EVENING
    quote = cache.latest_close("AAPL")

    assert provider.calls == ["AAPL"]
    assert quote.close == Decimal("231.47") and quote.stale is False


def test_cache_survives_a_new_session(session):
    """The cache lives in the database, not in the object: a later request still hits it."""
    provider, clock = FakeProvider(), Clock(MONDAY_MORNING)
    make_cache(session, provider, clock).latest_close("AAPL")

    with Session(session.get_bind()) as later_request:
        make_cache(later_request, provider, clock).latest_close("AAPL")
    assert provider.calls == ["AAPL"]


def test_next_new_york_day_fetches_again_and_updates_the_row(session):
    provider, clock = FakeProvider(), Clock(MONDAY_MORNING)
    cache = make_cache(session, provider, clock)
    cache.latest_close("AAPL")

    provider.close, provider.as_of = Decimal("233.10"), date(2026, 10, 26)
    clock.now = TUESDAY_JUST_AFTER_MIDNIGHT
    quote = cache.latest_close("AAPL")

    assert provider.calls == ["AAPL", "AAPL"]
    assert quote.close == Decimal("233.10")
    assert session.scalars(select(Price)).all() == [session.get(Price, "AAPL")]  # still one row
    assert session.get(Price, "AAPL").fetched_on == date(2026, 10, 27)


def test_symbols_are_matched_uppercase(session):
    provider, clock = FakeProvider(), Clock(MONDAY_MORNING)
    cache = make_cache(session, provider, clock)
    cache.latest_close("aapl")
    cache.latest_close(" AAPL ")

    assert provider.calls == ["AAPL"]
    assert session.get(Price, "AAPL") is not None


def test_api_down_falls_back_to_cached_price_marked_stale(session):
    provider, clock = FakeProvider(), Clock(MONDAY_MORNING)
    cache = make_cache(session, provider, clock)
    cache.latest_close("AAPL")

    provider.down = True
    clock.now = TUESDAY_JUST_AFTER_MIDNIGHT  # cache is from yesterday, so it tries the API
    quote = cache.latest_close("AAPL")

    assert provider.calls == ["AAPL", "AAPL"]
    assert quote == PriceQuote(
        symbol="AAPL", close=Decimal("231.47"), as_of=date(2026, 10, 23), stale=True
    )
    # A failed attempt doesn't count as today's fetch: the row is unchanged.
    assert session.get(Price, "AAPL").fetched_on == date(2026, 10, 26)


def test_api_down_with_nothing_cached_raises(session):
    provider = FakeProvider()
    provider.down = True
    with pytest.raises(MarketDataError, match="Could not reach"):
        make_cache(session, provider, Clock(MONDAY_MORNING)).latest_close("AAPL")
    assert session.get(Price, "AAPL") is None
