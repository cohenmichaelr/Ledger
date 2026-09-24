"""Trades endpoints — YOUR Week 1 work lives here.

See README "Week 1" and tests/test_trades.py for the spec.
"""

from fastapi import APIRouter, HTTPException, status

from ledger.db import SessionDep
from ledger.schemas import TradeCreate, TradeRead

router = APIRouter(prefix="/trades", tags=["trades"])


@router.post("", response_model=TradeRead, status_code=status.HTTP_201_CREATED)
def create_trade(payload: TradeCreate, session: SessionDep) -> TradeRead:
    # TODO(week1): build a models.Trade from payload, add, commit, refresh, return it.
    #   Hint: models.Trade(**payload.model_dump())  (** is like spreading props into a constructor)
    #   Normalize the symbol to uppercase before saving.
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("", response_model=list[TradeRead])
def list_trades(session: SessionDep, symbol: str | None = None):
    # TODO(week1): select(models.Trade), optionally filter by symbol, order by executed_at.
    #   Hint: session.scalars(stmt).all()
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/{trade_id}", response_model=TradeRead)
def get_trade(trade_id: int, session: SessionDep):
    # TODO(week1): session.get(models.Trade, trade_id); 404 if None.
    raise HTTPException(status_code=501, detail="Not implemented yet")
