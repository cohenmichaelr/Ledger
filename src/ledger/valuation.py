"""Valuation math: market value and unrealized P&L of open holdings at given prices.

Pure function, like positions.py: prices are passed in, so there is no DB or HTTP here.
"""

from collections.abc import Mapping
from decimal import Decimal

from ledger.market_data import PriceQuote
from ledger.positions import COST_PLACES, average_cost
from ledger.schemas import PortfolioValue, PositionValue


def value_holdings(
    portfolio_id: int,
    holdings: Mapping[str, tuple[Decimal, Decimal]],
    quotes: Mapping[str, PriceQuote],
) -> PortfolioValue:
    """Value each holding (symbol -> (quantity, cost)) at its quote's close.

    unrealized P&L = market value - cost basis. Figures are rounded to 6 places per symbol and
    each total is the sum of the rounded figures, so the parts always add up (as in /pnl).
    """
    positions = []
    for symbol, (quantity, cost) in holdings.items():
        quote = quotes[symbol]
        market_value = (quantity * quote.close).quantize(COST_PLACES)
        cost_basis = cost.quantize(COST_PLACES)
        positions.append(
            PositionValue(
                symbol=symbol,
                quantity=quantity,
                avg_cost=average_cost(quantity, cost),
                cost_basis=cost_basis,
                # Same 6 places as everything else, whether the close came from the API
                # ("343.91") or the cache's NUMERIC(18, 6) column ("343.910000")
                price=quote.close.quantize(COST_PLACES),
                price_as_of=quote.as_of,
                price_stale=quote.stale,
                market_value=market_value,
                unrealized_pnl=market_value - cost_basis,
            )
        )

    def total(field: str) -> Decimal:
        # getattr(obj, "name") reads an attribute by name, like reflection's GetProperty
        return sum((getattr(p, field) for p in positions), Decimal(0)).quantize(COST_PLACES)

    return PortfolioValue(
        portfolio_id=portfolio_id,
        positions=positions,
        total_market_value=total("market_value"),
        total_cost_basis=total("cost_basis"),
        total_unrealized_pnl=total("unrealized_pnl"),
    )
