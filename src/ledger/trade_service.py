"""Adding trades to a portfolio: insert, check no position goes short, all or nothing.

Shared by /trades/import and /portfolios/{id}/trades. C# analogy: a service class the
controllers call, rather than duplicating the logic in each one.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.csv_import import RowError
from ledger.models import Trade
from ledger.positions import OversellError, compute_positions
from ledger.schemas import Position, TradeCreate


class TradesRejected(ValueError):
    def __init__(self, errors: list[RowError]):
        self.errors = errors
        super().__init__(errors[0].reason)


def add_trades(
    session: Session, portfolio_id: int, entries: Sequence[tuple[int | None, TradeCreate]]
) -> tuple[list[Trade], list[Position]]:
    """Add (row number, trade) entries to a portfolio and commit.

    Returns the new trades and the portfolio's open positions. If any SELL exceeds the
    quantity held, nothing is saved and TradesRejected names the offending row.
    """
    row_of: dict[Trade, int | None] = {}  # ORM objects hash by identity, so they work as keys
    for row, payload in entries:
        trade = Trade(**payload.model_dump(), portfolio_id=portfolio_id)
        trade.symbol = trade.symbol.upper()
        session.add(trade)
        row_of[trade] = row
    session.flush()  # send the INSERTs (assigns ids) without committing, so we can still roll back

    # Ids follow input order, so equal timestamps keep their order within a file.
    stmt = (
        select(Trade)
        .where(Trade.portfolio_id == portfolio_id)
        .order_by(Trade.executed_at, Trade.id)
    )
    try:
        positions = compute_positions(session.scalars(stmt))
    except OversellError as exc:
        session.rollback()
        raise TradesRejected([RowError(row_of.get(exc.trade), str(exc))]) from None

    session.commit()
    return list(row_of), positions  # dicts keep insertion order, so trades are in input order
