"""ORM models (tables).

C# analogy: EF Core entity classes.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ledger.db import Base


class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ForeignKey = a real FK constraint in the DB (like a required navigation property's FK in EF)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[Side] = mapped_column(Enum(Side))
    # Money/quantities use Decimal, never float (same reason you'd use decimal in C#)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Price(Base):
    """Latest end-of-day close per symbol, cached from the price provider (LED-302).

    One row per symbol, overwritten on each fetch. The symbol is the primary key, so
    `session.get(Price, "AAPL")` finds the row directly (like EF Core's Find()).
    """

    __tablename__ = "prices"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    as_of: Mapped[date] = mapped_column(Date)  # trading day the close is from
    # New York calendar date of the fetch. Stored as a plain date because SQLite drops the
    # timezone from datetimes, which would make "was this fetched today?" unreliable.
    fetched_on: Mapped[date] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # for debugging
