"""
ファイルパス: tests/test_order_sync.py
概要: 注文同期のテスト
説明: sync_with_exchange機能を検証
関連ファイル: src/order_sync.py
"""

from unittest.mock import MagicMock

import pytest
from src.order_sync import sync_with_exchange, _match_order_to_grid
from src.grid_strategy import GridStrategy


@pytest.fixture
def strategy():
    return GridStrategy(
        symbol="BTCUSDT",
        current_price=50000.0,
        lower_price=45000.0,
        upper_price=55000.0,
        grid_count=10,
        investment_amount=1000.0,
    )


@pytest.fixture
def order_manager(strategy):
    client = MagicMock()
    client.get_open_orders.return_value = []
    om = MagicMock(client=client, strategy=strategy, _active_orders={})

    def _get_ids():
        return set(om._active_orders.keys())

    def _remove(oid):
        om._active_orders.pop(oid, None)

    om.get_active_order_ids.side_effect = _get_ids
    om.remove_order.side_effect = _remove
    return om


def test_sync_with_exchange_empty(order_manager, strategy):
    registered, removed = sync_with_exchange(order_manager, strategy)
    assert registered == 0
    assert removed == 0


def test_sync_registers_exchange_orders(order_manager, strategy):
    order_manager.client.get_open_orders.return_value = [
        {"orderId": 500, "side": "BUY", "price": "46000.00", "origQty": "0.002", "status": "NEW"},
    ]
    registered, removed = sync_with_exchange(order_manager, strategy)
    assert registered == 1
    order_manager.register_order.assert_called_once_with(
        order_id=500,
        grid_level=1,
        side="BUY",
        price=46000.0,
        quantity=0.002,
        status="NEW",
    )


def test_sync_removes_stale_orders(order_manager, strategy):
    order_manager._active_orders = {999: MagicMock()}
    order_manager.client.get_open_orders.return_value = []
    registered, removed = sync_with_exchange(order_manager, strategy)
    assert removed == 1
    assert 999 not in order_manager._active_orders


def test_sync_handles_filled_orders(order_manager, strategy):
    order_manager.client.get_open_orders.return_value = [
        {
            "orderId": 600,
            "side": "BUY",
            "price": "46000.00",
            "origQty": "0.002",
            "status": "FILLED",
        },
    ]
    sync_with_exchange(order_manager, strategy)
    assert strategy.grids[1].position_filled is True


def test_match_order_to_grid_buy(strategy):
    level = _match_order_to_grid(46000.0, strategy, "BUY")
    assert level == 1


def test_match_order_to_grid_sell(strategy):
    level = _match_order_to_grid(47000.0, strategy, "SELL")
    assert level == 1


def test_match_order_to_grid_no_match():
    s = GridStrategy("BTCUSDT", 50000.0, 45000.0, 55000.0, 10, 1000.0)
    assert _match_order_to_grid(99999.0, s, "BUY") is None


def test_sync_api_failure(order_manager, strategy):
    order_manager.client.get_open_orders.side_effect = Exception("API Error")
    registered, removed = sync_with_exchange(order_manager, strategy)
    assert registered == 0
    assert removed == 0
