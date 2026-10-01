"""Unit tests for FIFO position and realized P&L math (no DB, no HTTP)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from ledger.models import Side
from ledger.positions import OversellError, compute_positions, compute_realized_pnl


def trade(symbol, side, quantity, price):
    # SimpleNamespace = a throwaway object with attributes, like an anonymous type in C#
    return SimpleNamespace(
        symbol=symbol, side=Side(side), quantity=Decimal(quantity), price=Decimal(price)
    )


def test_buys_average_their_cost():
    [pos] = compute_positions(
        [trade("AAPL", "BUY", "10", "100"), trade("AAPL", "BUY", "10", "110")]
    )
    assert pos.quantity == Decimal("20")
    assert pos.avg_cost == Decimal("105")


def test_buys_only_keeps_symbols_separate_and_sorted():
    positions = compute_positions(
        [
            trade("MSFT", "BUY", "5", "400"),
            trade("AAPL", "BUY", "10", "100"),
            trade("MSFT", "BUY", "5", "420"),
        ]
    )
    assert [(p.symbol, p.quantity, p.avg_cost) for p in positions] == [
        ("AAPL", Decimal("10"), Decimal("100")),
        ("MSFT", Decimal("10"), Decimal("410")),
    ]


def test_partial_sell_single_lot_keeps_avg_cost():
    [pos] = compute_positions(
        [trade("AAPL", "BUY", "10", "100"), trade("AAPL", "SELL", "4", "130")]
    )
    assert pos.quantity == Decimal("6")
    assert pos.avg_cost == Decimal("100")  # the sell price doesn't affect cost basis


def test_partial_sell_across_lots_uses_fifo_avg_cost():
    [pos] = compute_positions(
        [
            trade("AAPL", "BUY", "10", "100"),
            trade("AAPL", "BUY", "10", "110"),
            trade("AAPL", "SELL", "15", "120"),
        ]
    )
    # FIFO: the 10 @ 100 lot is sold first, then 5 of the 110 lot -> 5 @ 110 remain.
    # Average cost moves from 105 to 110; a weighted-average method would keep 105.
    assert pos.quantity == Decimal("5")
    assert pos.avg_cost == Decimal("110")


def test_full_close_then_reopen_starts_fresh_cost_basis():
    [pos] = compute_positions(
        [
            trade("AAPL", "BUY", "10", "100"),
            trade("AAPL", "SELL", "10", "150"),
            trade("AAPL", "BUY", "5", "200"),
        ]
    )
    # nothing from the closed 100 lot may leak into the new position
    assert pos.quantity == Decimal("5")
    assert pos.avg_cost == Decimal("200")


def test_fully_closed_position_is_excluded():
    positions = compute_positions(
        [
            trade("AAPL", "BUY", "10", "100"),
            trade("MSFT", "BUY", "5", "400"),
            trade("MSFT", "SELL", "5", "420"),
        ]
    )
    assert [p.symbol for p in positions] == ["AAPL"]


def test_avg_cost_is_rounded_to_six_places():
    [pos] = compute_positions(
        [
            trade("AAPL", "BUY", "1", "1"),
            trade("AAPL", "BUY", "1", "1"),
            trade("AAPL", "BUY", "1", "2"),
        ]
    )
    assert pos.avg_cost == Decimal("1.333333")


def test_selling_more_than_held_raises():
    sell = trade("AAPL", "SELL", "11", "100")
    with pytest.raises(OversellError) as exc:
        compute_positions([trade("AAPL", "BUY", "10", "100"), sell])
    assert exc.value.trade is sell


# --- Realized P&L ----------------------------------------------------------------------------


def pnl_by_symbol(trades):
    symbols, total = compute_realized_pnl(trades)
    return {s.symbol: s.realized_pnl for s in symbols}, total


def test_full_close_realizes_whole_gain():
    pnl, total = pnl_by_symbol(
        [trade("AAPL", "BUY", "10", "100"), trade("AAPL", "SELL", "10", "150")]
    )
    assert pnl == {"AAPL": Decimal("500")}
    assert total == Decimal("500")


def test_partial_sell_realizes_only_the_sold_quantity():
    pnl, _ = pnl_by_symbol([trade("AAPL", "BUY", "10", "100"), trade("AAPL", "SELL", "4", "130")])
    assert pnl == {"AAPL": Decimal("120")}  # 4 x (130 - 100)


def test_sell_across_lots_matches_oldest_first():
    pnl, _ = pnl_by_symbol(
        [
            trade("AAPL", "BUY", "10", "100"),
            trade("AAPL", "BUY", "10", "110"),
            trade("AAPL", "SELL", "15", "120"),
        ]
    )
    # FIFO: 10 x (120 - 100) + 5 x (120 - 110) = 200 + 50.
    # Matching the newest lot first (LIFO) would give 10 x 10 + 5 x 20 = 200 instead.
    assert pnl == {"AAPL": Decimal("250")}


def test_loss_is_negative():
    pnl, total = pnl_by_symbol(
        [trade("MSFT", "BUY", "5", "400"), trade("MSFT", "SELL", "5", "380")]
    )
    assert pnl == {"MSFT": Decimal("-100")}
    assert total == Decimal("-100")


def test_close_then_reopen_uses_new_lot():
    pnl, _ = pnl_by_symbol(
        [
            trade("AAPL", "BUY", "10", "100"),
            trade("AAPL", "SELL", "10", "150"),  # +500
            trade("AAPL", "BUY", "5", "200"),
            trade("AAPL", "SELL", "5", "190"),  # -50, against the 200 lot, not the 100 one
        ]
    )
    assert pnl == {"AAPL": Decimal("450")}


def test_symbols_are_sorted_and_total_sums_them():
    symbols, total = compute_realized_pnl(
        [
            trade("MSFT", "BUY", "5", "400"),
            trade("AAPL", "BUY", "10", "100"),
            trade("MSFT", "SELL", "5", "380"),  # -100
            trade("AAPL", "SELL", "10", "150"),  # +500
        ]
    )
    assert [s.symbol for s in symbols] == ["AAPL", "MSFT"]
    assert total == Decimal("400")


def test_symbols_never_sold_are_not_listed():
    symbols, total = compute_realized_pnl(
        [trade("AAPL", "BUY", "10", "100"), trade("MSFT", "BUY", "5", "400")]
    )
    assert symbols == []
    assert total == Decimal("0")


def test_realized_pnl_is_rounded_to_six_places():
    pnl, _ = pnl_by_symbol(
        [trade("AAPL", "BUY", "0.333333", "1.000001"), trade("AAPL", "SELL", "0.333333", "2")]
    )
    # 0.333333 x 0.999999 = 0.333332666667 exactly; stored precision is 6 places
    assert pnl == {"AAPL": Decimal("0.333333")}


def test_realized_pnl_rejects_oversell():
    with pytest.raises(OversellError):
        compute_realized_pnl([trade("AAPL", "SELL", "1", "100")])
