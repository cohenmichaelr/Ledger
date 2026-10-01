"""API request/response shapes (Pydantic).

C# analogy: DTOs with DataAnnotations validation. Keep these separate from ORM models.
"""

from datetime import datetime
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
