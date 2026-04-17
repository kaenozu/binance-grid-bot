"""停止時の成行決済ロジックのテスト"""

from unittest.mock import MagicMock

import pytest

from src.grid_strategy import GridStrategy
from src.position_closer import close_open_positions
from tests.conftest import BASE_PRICE, LOWER_PRICE, UPPER_PRICE


def test_close_open_positions_uses_restored_buy_quantity():
    strategy = GridStrategy(
        symbol="ETHJPY",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )
    grid = strategy.grids[5]
    grid.position_filled = True
    grid.filled_quantity = None
    grid.buy_order_id = 12345

    client = MagicMock()
    client.get_symbol_info.return_value = {
        "symbol": "ETHJPY",
        "status": "TRADING",
        "base_asset": "ETH",
        "quote_asset": "JPY",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "min_notional": 10.0,
        "tick_size": 1.0,
    }
    client.get_account_balance.return_value = {
        "ETH": {"free": 0.00134, "locked": 0.0},
        "JPY": {"free": 9785.89, "locked": 0.0},
    }
    client.place_order.return_value = {
        "orderId": 999,
        "executedQty": "0.00134",
        "avgPrice": "372000",
        "price": "372000",
    }

    portfolio = MagicMock()
    portfolio.find_matching_buy_trade.return_value = MagicMock(quantity=0.00134)
    portfolio.record_trade.return_value = None

    closed = close_open_positions(client, strategy, portfolio)

    assert closed == 1
    client.place_order.assert_called_once()
    assert client.place_order.call_args.kwargs["quantity"] == pytest.approx(0.00134)


def test_close_open_positions_skips_dust_balance():
    strategy = GridStrategy(
        symbol="ETHJPY",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )
    strategy.grids[5].position_filled = True

    client = MagicMock()
    client.get_symbol_info.return_value = {
        "symbol": "ETHJPY",
        "status": "TRADING",
        "base_asset": "ETH",
        "quote_asset": "JPY",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "min_notional": 10.0,
        "tick_size": 1.0,
    }
    client.get_account_balance.return_value = {
        "ETH": {"free": 0.00000866, "locked": 0.0},
        "JPY": {"free": 9785.89, "locked": 0.0},
    }

    portfolio = MagicMock()

    closed = close_open_positions(client, strategy, portfolio)

    assert closed == 0
    client.place_order.assert_not_called()


def test_close_open_positions_decrements_available_across_multiple_positions():
    strategy = GridStrategy(
        symbol="ETHJPY",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )
    strategy.grids[2].position_filled = True
    strategy.grids[4].position_filled = True
    strategy.grids[2].filled_quantity = 0.001
    strategy.grids[4].filled_quantity = 0.002

    client = MagicMock()
    client.get_symbol_info.return_value = {
        "symbol": "ETHJPY",
        "status": "TRADING",
        "base_asset": "ETH",
        "quote_asset": "JPY",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "min_notional": 10.0,
        "tick_size": 1.0,
    }
    client.get_account_balance.return_value = {
        "ETH": {"free": 0.003, "locked": 0.0},
        "JPY": {"free": 9785.89, "locked": 0.0},
    }
    client.place_order.side_effect = [
        {"orderId": 1, "executedQty": "0.001", "avgPrice": "372000", "price": "372000"},
        {"orderId": 2, "executedQty": "0.002", "avgPrice": "372000", "price": "372000"},
    ]

    portfolio = MagicMock()
    portfolio.find_matching_buy_trade.side_effect = [
        MagicMock(quantity=0.001),
        MagicMock(quantity=0.002),
    ]
    portfolio.record_trade.return_value = None

    closed = close_open_positions(client, strategy, portfolio)

    assert closed == 2
    assert client.place_order.call_count == 2
    assert client.place_order.call_args_list[0].kwargs["quantity"] == pytest.approx(0.001)
    assert client.place_order.call_args_list[1].kwargs["quantity"] == pytest.approx(0.002)
