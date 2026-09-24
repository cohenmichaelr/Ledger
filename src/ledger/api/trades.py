"""Trades endpoints: record and look up executed trades."""

from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ledger import models
from ledger.db import SessionDep
from ledger.schemas import TradeCreate, TradeRead

router = APIRouter(prefix="/trades", tags=["trades"])


@router.post("", response_model=TradeRead, status_code=status.HTTP_201_CREATED)
def create_trade(payload: TradeCreate, session: SessionDep) -> models.Trade:
    # By the time we get here FastAPI has already validated the JSON against TradeCreate
    # (quantity > 0, etc.) and returned 422 if it failed -- like [ApiController] model validation.

    # model_dump() -> dict; ** unpacks it into keyword args: Trade(symbol=..., side=..., ...)
    trade = models.Trade(**payload.model_dump())
    trade.symbol = trade.symbol.upper()

    session.add(trade)  # stage the INSERT (like dbContext.Trades.Add)
    session.commit()  # write it (SaveChanges)
    session.refresh(trade)  # reload DB-generated fields: id, created_at
    return trade  # response_model=TradeRead converts the ORM object to JSON


@router.get("", response_model=list[TradeRead])
def list_trades(session: SessionDep, symbol: str | None = None) -> Sequence[models.Trade]:
    # A parameter that isn't in the path becomes a query-string param: GET /trades?symbol=MSFT
    stmt = select(models.Trade).order_by(models.Trade.executed_at, models.Trade.id)
    if symbol:
        # Statements are immutable builders -- .where() returns a new one (like chaining LINQ)
        stmt = stmt.where(models.Trade.symbol == symbol.upper())
    return session.scalars(stmt).all()  # scalars() = rows as Trade objects, not tuples


@router.get("/{trade_id}", response_model=TradeRead)
def get_trade(trade_id: int, session: SessionDep) -> models.Trade:
    trade = session.get(models.Trade, trade_id)  # primary-key lookup (like DbSet.Find)
    if trade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    return trade
