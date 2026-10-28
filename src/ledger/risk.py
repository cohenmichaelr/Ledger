"""Risk metrics over a valued portfolio. Pure functions: no DB, HTTP or prices fetched here.

LED-401 exposure and concentration. GET /portfolios/{id}/risk (LED-403) will serve these.
"""

from decimal import ROUND_FLOOR, Decimal

from ledger.schemas import Exposure, PortfolioValue, SymbolExposure

HUNDREDTHS = Decimal("0.01")
WHOLE = 10_000  # 100.00% in hundredths (underscores in numbers are just digit separators)


def compute_exposure(value: PortfolioValue) -> Exposure:
    """Each symbol's share of market value as a %, and the largest position.

    Percents have 2 places and always sum to exactly 100.00 (largest-remainder rounding):
    round every share down to the hundredth, then hand the hundredths still missing, one each,
    to the symbols that lost the most in rounding. Rounding each share on its own can miss:
    three equal positions would be 33.33 x 3 = 99.99. Ties go to the earlier symbol.

    The concentration figure is the position with the largest market value (ties: earlier
    symbol). An empty portfolio, or one worth 0, has no exposures and no concentration.
    """
    total = value.total_market_value
    if total <= 0:
        return Exposure(exposures=[], concentration=None)

    shares = {p.symbol: p.market_value / total * 100 for p in value.positions}
    floors = {s: share.quantize(HUNDREDTHS, rounding=ROUND_FLOOR) for s, share in shares.items()}
    missing = WHOLE - int(sum(floors.values()) / HUNDREDTHS)  # hundredths short of 100.00

    # Largest remainder first; for equal remainders, the earlier symbol. A key returning a
    # tuple sorts by its first item, then the second (like OrderByDescending().ThenBy()).
    by_remainder = sorted(shares, key=lambda s: (-(shares[s] - floors[s]), s))
    for symbol in by_remainder[:missing]:
        floors[symbol] += HUNDREDTHS

    exposures = [
        SymbolExposure(symbol=p.symbol, market_value=p.market_value, percent=floors[p.symbol])
        for p in sorted(value.positions, key=lambda p: p.symbol)
    ]
    largest = min(exposures, key=lambda e: (-e.market_value, e.symbol))
    return Exposure(exposures=exposures, concentration=largest)
