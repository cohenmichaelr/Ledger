"""Portfolio lookups. Until there are portfolio endpoints, every trade goes into "Default"."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.models import Portfolio

DEFAULT_PORTFOLIO = "Default"


def default_portfolio(session: Session) -> Portfolio:
    """Return the Default portfolio, creating it on first use (not committed here)."""
    portfolio = session.scalars(
        select(Portfolio).where(Portfolio.name == DEFAULT_PORTFOLIO)
    ).first()
    if portfolio is None:
        portfolio = Portfolio(name=DEFAULT_PORTFOLIO)
        session.add(portfolio)
        session.flush()  # INSERT now so portfolio.id is assigned; the caller's commit keeps it
    return portfolio
