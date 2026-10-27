"""API request/response shapes (Pydantic).

C# analogy: DTOs with DataAnnotations validation. Keep these separate from ORM models.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ledger.models import Side


class TradeCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    side: Side
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    executed_at: datetime


class TradeRead(TradeCreate):
    model_config = ConfigDict(from_attributes=True)  # allows TradeRead.model_validate(orm_obj)

    id: int
    portfolio_id: int


class Position(BaseModel):
    symbol: str
    quantity: Decimal
    avg_cost: Decimal


class SymbolPnl(BaseModel):
    symbol: str
    realized_pnl: Decimal


class RealizedPnl(BaseModel):
    portfolio_id: int
    symbols: list[SymbolPnl]
    total: Decimal


class PositionValue(BaseModel):
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    cost_basis: Decimal
    price: Decimal  # latest end-of-day close
    price_as_of: date  # trading day of that close
    price_stale: bool  # True when the price API failed and the cached price was used
    market_value: Decimal
    unrealized_pnl: Decimal


class PortfolioValue(BaseModel):
    portfolio_id: int
    positions: list[PositionValue]
    total_market_value: Decimal
    total_cost_basis: Decimal
    total_unrealized_pnl: Decimal


# Annotated[type, constraints] attaches validation to a type, like [StringLength] on a C# property
PortfolioName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]


class PortfolioCreate(BaseModel):
    name: PortfolioName


class PortfolioRead(PortfolioCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
