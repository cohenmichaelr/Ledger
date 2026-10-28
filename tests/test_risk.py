"""LED-401: exposure by symbol and the concentration figure. Pure functions, no API or DB."""

from datetime import date
from decimal import Decimal

from ledger.risk import compute_exposure
from ledger.schemas import PortfolioValue, PositionValue


def portfolio(**market_values: str) -> PortfolioValue:
    """A valued portfolio with just the fields exposure reads: symbol -> market value."""
    positions = [
        PositionValue(
            symbol=symbol,
            quantity=Decimal(1),
            avg_cost=Decimal(mv),
            cost_basis=Decimal(mv),
            price=Decimal(mv),
            price_as_of=date(2026, 10, 23),
            price_stale=False,
            market_value=Decimal(mv),
            unrealized_pnl=Decimal(0),
        )
        for symbol, mv in sorted(market_values.items())
    ]
    total = sum((p.market_value for p in positions), Decimal(0))
    return PortfolioValue(
        portfolio_id=1,
        positions=positions,
        total_market_value=total,
        total_cost_basis=total,
        total_unrealized_pnl=Decimal(0),
    )


def percents(exposure) -> dict[str, Decimal]:
    return {e.symbol: e.percent for e in exposure.exposures}


def test_sample_portfolio_exposure_matches_hand_check():
    # Sample CSV at AAPL 200.00, NVDA 120.50 (see test_valuation.py): 3000 + 2410 = 5410
    # AAPL 3000/5410 = 55.4529%, NVDA 2410/5410 = 44.5471%; floors 55.45 + 44.54 = 99.99,
    # and the spare hundredth goes to NVDA, whose remainder is larger.
    exposure = compute_exposure(portfolio(AAPL="3000", NVDA="2410"))

    assert percents(exposure) == {"AAPL": Decimal("55.45"), "NVDA": Decimal("44.55")}
    assert exposure.concentration is not None
    assert exposure.concentration.symbol == "AAPL"
    assert exposure.concentration.percent == Decimal("55.45")
    assert exposure.concentration.market_value == Decimal("3000")


def test_three_equal_positions_sum_to_exactly_100():
    # Plain rounding gives 33.33 x 3 = 99.99; the spare hundredth goes to the first symbol
    exposure = compute_exposure(portfolio(AAA="100", BBB="100", CCC="100"))

    assert percents(exposure) == {
        "AAA": Decimal("33.34"),
        "BBB": Decimal("33.33"),
        "CCC": Decimal("33.33"),
    }
    assert sum(percents(exposure).values()) == 100


def test_tie_for_largest_flags_the_first_symbol_alphabetically():
    exposure = compute_exposure(portfolio(MSFT="500", AAPL="500", NVDA="100"))
    assert exposure.concentration.symbol == "AAPL"


def test_single_position_is_100_percent_and_the_concentration():
    exposure = compute_exposure(portfolio(AAPL="1234.56"))

    assert percents(exposure) == {"AAPL": Decimal("100.00")}
    assert exposure.concentration.symbol == "AAPL"


def test_empty_portfolio_has_no_exposure_and_no_concentration():
    exposure = compute_exposure(portfolio())

    assert exposure.exposures == []
    assert exposure.concentration is None


def test_many_small_positions_still_sum_to_exactly_100():
    # 7 positions of 1/7 each: plain rounding gives 14.29 x 7 = 100.03, outside +/-0.01
    symbols = {f"S{i}": "10" for i in range(7)}
    exposure = compute_exposure(portfolio(**symbols))

    assert sum(percents(exposure).values()) == Decimal("100.00")
    assert all(p in (Decimal("14.28"), Decimal("14.29")) for p in percents(exposure).values())


def test_uneven_values_sum_to_exactly_100_and_stay_close_to_true_share():
    values = {"A": "333.33", "B": "0.01", "C": "1000000", "D": "45.678", "E": "12.5"}
    exposure = compute_exposure(portfolio(**values))

    total = sum(Decimal(v) for v in values.values())
    assert sum(percents(exposure).values()) == Decimal("100.00")
    for symbol, percent in percents(exposure).items():
        true_share = Decimal(values[symbol]) / total * 100
        assert abs(percent - true_share) < Decimal("0.01")  # each within one hundredth
