"""Portfolio endpoints: portfolios, their trades, realized P&L and valuation."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from ledger import models
from ledger.api.errors import unprocessable
from ledger.csv_import import CsvImportError, RowError, parse_trades_csv
from ledger.db import SessionDep
from ledger.market_data import PriceProvider
from ledger.positions import compute_holdings, compute_realized_pnl
from ledger.price_cache import get_price_provider
from ledger.schemas import (
    PortfolioCreate,
    PortfolioRead,
    PortfolioValue,
    RealizedPnl,
    TradeCreate,
    TradeRead,
)
from ledger.trade_service import TradesRejected, add_trades
from ledger.valuation import value_holdings

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def get_portfolio(portfolio_id: int, session: SessionDep) -> models.Portfolio:
    """Dependency: load the portfolio named in the path, or 404."""
    portfolio = session.get(models.Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
    return portfolio


# Routes declare `portfolio: PortfolioDep` and receive the loaded row (like an action filter
# that resolves the entity). FastAPI shares one session per request across dependencies.
PortfolioDep = Annotated[models.Portfolio, Depends(get_portfolio)]


@dataclass
class TradeUpload:
    entries: list[tuple[int | None, TradeCreate]]  # (CSV row number or None, trade)
    from_csv: bool


async def read_trade_upload(request: Request) -> TradeUpload:
    """Dependency: parse the body as one JSON trade or a multipart CSV upload.

    `async` because reading the request body is awaitable; the route itself stays sync.
    """
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        try:
            trade = TradeCreate.model_validate_json(await request.body())
        except ValidationError as exc:
            # Same 422 shape FastAPI produces for a normal JSON body
            errors = exc.errors(include_url=False)
            body_errors = [{**e, "loc": ("body", *e["loc"])} for e in errors]
            raise RequestValidationError(body_errors) from None
        return TradeUpload(entries=[(None, trade)], from_csv=False)

    if content_type.startswith("multipart/form-data"):
        upload = (await request.form()).get("file")
        if not isinstance(upload, UploadFile):
            raise unprocessable([RowError(None, "multipart body needs a CSV in a 'file' field")])
        try:
            entries = parse_trades_csv(await upload.read())
        except CsvImportError as exc:
            raise unprocessable(exc.errors) from None
        return TradeUpload(entries=entries, from_csv=True)

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Send application/json (one trade) or multipart/form-data with a CSV 'file'",
    )


# FastAPI can't infer a body that is "JSON or a file", so describe both for /docs by hand.
TRADE_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/TradeCreate"}},
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            },
        },
    }
}


@router.post("", response_model=PortfolioRead, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: PortfolioCreate, session: SessionDep) -> models.Portfolio:
    portfolio = models.Portfolio(name=payload.name)
    session.add(portfolio)
    try:
        session.commit()
    except IntegrityError:  # the unique constraint on name; the DB is the source of truth
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A portfolio named {payload.name!r} already exists",
        ) from None
    session.refresh(portfolio)  # load DB-generated created_at
    return portfolio


@router.get("", response_model=list[PortfolioRead])
def list_portfolios(session: SessionDep) -> Sequence[models.Portfolio]:
    return session.scalars(select(models.Portfolio).order_by(models.Portfolio.id)).all()


@router.post(
    "/{portfolio_id}/trades",
    response_model=TradeRead | list[TradeRead],
    status_code=status.HTTP_201_CREATED,
    openapi_extra=TRADE_UPLOAD_BODY,
)
def add_portfolio_trades(
    portfolio: PortfolioDep,  # resolved first, so an unknown id is a 404 before the body is read
    upload: Annotated[TradeUpload, Depends(read_trade_upload)],
    session: SessionDep,
) -> models.Trade | list[models.Trade]:
    """Add one trade (JSON) or a CSV of trades (multipart `file`), all or nothing.

    Returns the created trade, or the list of created trades for a CSV.
    """
    try:
        trades, _ = add_trades(session, portfolio.id, upload.entries)
    except TradesRejected as exc:
        raise unprocessable(exc.errors) from None
    return trades if upload.from_csv else trades[0]


@router.get("/{portfolio_id}/trades", response_model=list[TradeRead])
def list_portfolio_trades(portfolio: PortfolioDep, session: SessionDep) -> Sequence[models.Trade]:
    """Trades in the portfolio, newest first."""
    stmt = (
        select(models.Trade)
        .where(models.Trade.portfolio_id == portfolio.id)
        .order_by(models.Trade.executed_at.desc(), models.Trade.id.desc())
    )
    return session.scalars(stmt).all()


def _trades_in_execution_order(session: SessionDep, portfolio_id: int) -> Sequence[models.Trade]:
    stmt = (
        select(models.Trade)
        .where(models.Trade.portfolio_id == portfolio_id)
        .order_by(models.Trade.executed_at, models.Trade.id)  # FIFO needs execution order
    )
    return session.scalars(stmt).all()


@router.get("/{portfolio_id}/pnl", response_model=RealizedPnl)
def get_realized_pnl(portfolio: PortfolioDep, session: SessionDep) -> RealizedPnl:
    """Realized P&L per symbol and in total, matching sells to buys first-in, first-out.

    Only symbols with at least one sell are listed. Oversells can't occur here: they are
    rejected with 422 when trades are added.
    """
    symbols, total = compute_realized_pnl(_trades_in_execution_order(session, portfolio.id))
    return RealizedPnl(portfolio_id=portfolio.id, symbols=symbols, total=total)


@router.get("/{portfolio_id}/value", response_model=PortfolioValue)
def get_portfolio_value(
    portfolio: PortfolioDep,  # resolved first, so an unknown id is a 404 before any price work
    session: SessionDep,
    prices: Annotated[PriceProvider, Depends(get_price_provider)],
) -> PortfolioValue:
    """Market value and unrealized P&L of each open position at its latest end-of-day close.

    Prices come through the price cache: at most one API call per symbol per day, and the
    cached price (with `price_stale: true`) when the API is down. If a symbol has no price at
    all, the response is 503 naming it.
    """
    holdings = compute_holdings(_trades_in_execution_order(session, portfolio.id))
    quotes = {symbol: prices.latest_close(symbol) for symbol in holdings}  # dict comprehension
    return value_holdings(portfolio.id, holdings, quotes)
