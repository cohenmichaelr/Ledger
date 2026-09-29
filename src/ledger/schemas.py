"""API request/response shapes (Pydantic).

C# analogy: DTOs with DataAnnotations validation. Keep these separate from ORM models.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

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
