"""
ファイルパス: tests/test_order_manager.py
概要: 注文管理のテスト
説明: 注文配置、約定チェック、キャンセル、クリーンアップを検証
関連ファイル: src/order_manager.py, tests/conftest.py
"""

import pytest
from unittest.mock import MagicMock, patch
from src.order_manager import OrderManager
from src.grid_strategy import GridStrategy


class TestOrderManager:
    """注文管理のテスト"""

    @pytest.fixture
    def strategy(self):
        return GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0,
        )

    @pytest.fixture
    def mock_client(self, strategy):
        client = MagicMock()
        client.get_symbol_info.return_value = {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "min_qty": 0.00001,
            "step_size": 0.00001,
            "tick_size": 0.01,
        }
        client.place_order.return_value = {
            "orderId": 99999,
            "price": "50000.00",
            "origQty": "0.002",
            "status": "NEW",
        }
        client.get_open_orders.return_value = []
        return client

    @pytest.fixture
    def order_manager(self, mock_client, strategy):
        return OrderManager(mock_client, strategy)

    def test_register_order(self, order_manager):
        order_manager.register_order(
            order_id=100,
            grid_level=3,
            side="BUY",
            price=47000.0,
            quantity=0.002,
            status="NEW",
        )
        assert 100 in order_manager.active_orders
        assert order_manager.active_orders[100].grid_level == 3

    def test_cleanup_filled_orders(self, order_manager):
        order_manager.register_order(100, 0, "BUY", 45000.0, 0.002, "FILLED")
        order_manager.register_order(101, 1, "BUY", 46000.0, 0.002, "NEW")

        order_manager.cleanup_filled_orders()
        assert 100 not in order_manager.active_orders
        assert 101 in order_manager.active_orders

    def test_check_order_fills_auto_cleanup(self, order_manager, mock_client):
        order_manager.register_order(100, 0, "BUY", 45000.0, 0.002, "NEW")

        mock_client.get_order.return_value = {
            "status": "FILLED",
            "price": "45000.00",
            "executedQty": "0.002",
        }

        fills = order_manager.check_order_fills()
        assert len(fills) == 1
        assert fills[0].grid == 0
        assert 100 not in order_manager.active_orders

    def test_cancel_all_orders(self, order_manager, mock_client):
        mock_client.get_open_orders.return_value = [
            {"orderId": 100},
            {"orderId": 101},
        ]
        canceled = order_manager.cancel_all_orders()
        assert canceled == 2
        assert mock_client.cancel_order.call_count == 2

    def test_get_active_order_count(self, order_manager):
        order_manager.register_order(100, 0, "BUY", 45000.0, 0.002, "NEW")
        order_manager.register_order(101, 1, "BUY", 46000.0, 0.002, "FILLED")
        assert order_manager.get_active_order_count() == 1

    def test_place_grid_orders(self, order_manager, mock_client):
        result = order_manager.place_grid_orders()
        assert result.placed > 0
        assert len(result.errors) == 0

    def test_place_grid_orders_no_symbol_info(self, order_manager, mock_client):
        mock_client.get_symbol_info.return_value = None
        result = order_manager.place_grid_orders()
        assert result.placed == 0
        assert len(result.errors) == 1
