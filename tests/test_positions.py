"""Unit tests for FIFO position math (no DB, no HTTP)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from ledger.models import Side
from ledger.positions import OversellError, compute_positions


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


def test_partial_sell_consumes_oldest_lot_first():
    [pos] = compute_positions(
        [
            trade("AAPL", "BUY", "10", "100"),
            trade("AAPL", "BUY", "10", "110"),
            trade("AAPL", "SELL", "15", "120"),
        ]
    )
    # 10 @ 100 fully sold, 5 of the 110 lot sold -> 5 @ 110 remain
    assert pos.quantity == Decimal("5")
    assert pos.avg_cost == Decimal("110")


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
