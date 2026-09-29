"""Trades endpoints: record and look up executed trades."""

from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, UploadFile, status
from sqlalchemy import select

from ledger import models
from ledger.api.errors import unprocessable
from ledger.csv_import import CsvImportError, parse_trades_csv
from ledger.db import SessionDep
from ledger.portfolios import default_portfolio
from ledger.schemas import Position, TradeCreate, TradeRead
from ledger.trade_service import TradesRejected, add_trades

router = APIRouter(prefix="/trades", tags=["trades"])


@router.post("/import", response_model=list[Position])
def import_trades(file: UploadFile, session: SessionDep) -> list[Position]:
    """Import a CSV of trades (all or nothing) and return the portfolio's open positions."""
    # UploadFile = a multipart/form-data file field (like IFormFile in ASP.NET)
    try:
        parsed = parse_trades_csv(file.file.read())
    except CsvImportError as exc:
        raise unprocessable(exc.errors) from None

    try:
        _, positions = add_trades(session, default_portfolio(session).id, parsed)
    except TradesRejected as exc:
        raise unprocessable(exc.errors) from None
    return positions


@router.post("", response_model=TradeRead, status_code=status.HTTP_201_CREATED)
def create_trade(payload: TradeCreate, session: SessionDep) -> models.Trade:
    # By the time we get here FastAPI has already validated the JSON against TradeCreate
    # (quantity > 0, etc.) and returned 422 if it failed -- like [ApiController] model validation.

    # model_dump() -> dict; ** unpacks it into keyword args: Trade(symbol=..., side=..., ...)
    trade = models.Trade(**payload.model_dump(), portfolio_id=default_portfolio(session).id)
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
