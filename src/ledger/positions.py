"""Position math: net quantity, FIFO average cost and realized P&L per symbol.

Pure functions over trades -- no DB or HTTP here, so the math is easy to unit test.
"""

from collections import defaultdict, deque
from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol

from ledger.models import Side
from ledger.schemas import Position, SymbolPnl

COST_PLACES = Decimal("0.000001")  # matches NUMERIC(18, 6)


class TradeLike(Protocol):
    """Anything with these attributes works (ORM Trade, TradeCreate, ...).

    C# analogy: an interface, but satisfied structurally -- classes don't have to declare it.
    """

    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal


class OversellError(ValueError):
    """A SELL is larger than the quantity held. Shorts are out of scope for v1."""

    def __init__(self, trade: TradeLike, held: Decimal):
        self.trade = trade
        super().__init__(
            f"SELL {_plain(trade.quantity)} {trade.symbol} exceeds position of {_plain(held)}"
        )


def _plain(value: Decimal) -> str:
    # normalize() drops trailing zeros (10.000000 -> 1E+1); the :f format spec undoes the exponent
    return f"{value.normalize():f}"


Lots = dict[str, deque[list[Decimal]]]  # symbol -> queue of [quantity, price] lots


def _match_fifo(trades: Iterable[TradeLike]) -> tuple[Lots, dict[str, Decimal]]:
    """Replay trades in execution order, matching each SELL against the oldest lots first.

    Returns the open lots per symbol and the realized P&L per symbol that has had a SELL.
    Every slice of a lot a SELL consumes realizes quantity x (sell price - lot price).
    """
    # defaultdict creates an empty deque on first use of a symbol
    lots: Lots = defaultdict(deque)
    realized: dict[str, Decimal] = defaultdict(Decimal)  # Decimal() is 0

    for trade in trades:
        queue = lots[trade.symbol]
        if trade.side == Side.BUY:
            queue.append([trade.quantity, trade.price])
            continue

        held = sum((lot[0] for lot in queue), Decimal(0))
        if trade.quantity > held:
            raise OversellError(trade, held)
        remaining = trade.quantity
        while remaining > 0:
            lot = queue[0]
            used = min(lot[0], remaining)
            realized[trade.symbol] += used * (trade.price - lot[1])
            lot[0] -= used
            remaining -= used
            if lot[0] == 0:
                queue.popleft()

    return lots, realized


def compute_positions(trades: Iterable[TradeLike]) -> list[Position]:
    """Open positions per symbol, sorted by symbol. Trades must be in execution order.

    Each BUY adds a lot; each SELL consumes lots oldest-first (FIFO). Average cost is the
    cost of the remaining lots divided by the quantity held. Closed positions are omitted.
    """
    lots, _ = _match_fifo(trades)  # _ = "ignore this value" by convention

    positions = []
    for symbol in sorted(lots):
        queue = lots[symbol]
        quantity = sum((q for q, _ in queue), Decimal(0))
        if quantity == 0:
            continue
        cost = sum((q * p for q, p in queue), Decimal(0))
        positions.append(
            Position(
                symbol=symbol, quantity=quantity, avg_cost=(cost / quantity).quantize(COST_PLACES)
            )
        )
    return positions


def compute_realized_pnl(trades: Iterable[TradeLike]) -> tuple[list[SymbolPnl], Decimal]:
    """Realized P&L per symbol (sorted, only symbols with a SELL) and the total.

    Trades must be in execution order. Each symbol is rounded to 6 places and the total is
    the sum of the rounded figures, so the parts always add up to the total.
    """
    _, realized = _match_fifo(trades)
    symbols = [
        SymbolPnl(symbol=symbol, realized_pnl=realized[symbol].quantize(COST_PLACES))
        for symbol in sorted(realized)
    ]
    total = sum((s.realized_pnl for s in symbols), Decimal(0)).quantize(COST_PLACES)
    return symbols, total
