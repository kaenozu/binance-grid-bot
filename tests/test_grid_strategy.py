"""
ファイルパス: tests/test_grid_strategy.py
概要: グリッド取引戦略のテスト
説明: グリッド計算、注文数量、アクティブグリッドのロジックを検証
関連ファイル: src/grid_strategy.py, tests/conftest.py
"""

import pytest
from src.grid_strategy import GridStrategy


class TestGridStrategy:
    """グリッド戦略のテスト"""

    def test_grid_initialization(self, grid_strategy):
        assert grid_strategy.symbol == "BTCUSDT"
        assert grid_strategy.lower_price == 45000.0
        assert grid_strategy.upper_price == 55000.0
        assert grid_strategy.grid_count == 10
        assert len(grid_strategy.grids) == 10

    def test_grid_spacing(self, grid_strategy):
        expected = (55000.0 - 45000.0) / 10
        assert grid_strategy.grid_spacing == expected

    def test_grid_prices(self, grid_strategy):
        assert grid_strategy.grids[0].buy_price == 45000.0
        assert grid_strategy.grids[9].buy_price == 54000.0
        assert grid_strategy.grids[1].buy_price == 46000.0

    def test_sell_prices(self, grid_strategy):
        assert grid_strategy.grids[0].sell_price == 46000.0
        assert grid_strategy.grids[9].sell_price is None

    def test_order_quantity(self, grid_strategy):
        qty = grid_strategy.get_order_quantity(50000.0, min_qty=0.00001, step_size=0.00001)
        assert abs(qty - 0.002) < 0.00001

    def test_order_quantity_respects_min_qty(self, grid_strategy):
        qty = grid_strategy.get_order_quantity(50000.0, min_qty=0.001, step_size=0.00001)
        assert qty >= 0.001

    def test_active_buy_grids(self, grid_strategy):
        buy_grids = grid_strategy.get_active_buy_grids()
        assert len(buy_grids) == 6
        assert all(g.buy_price <= 50000.0 for g in buy_grids)

    def test_active_sell_grids_empty(self, grid_strategy):
        assert len(grid_strategy.get_active_sell_grids()) == 0

    def test_active_sell_grids_after_fill(self, grid_strategy):
        grid_strategy.mark_position_filled(3, 12345)
        sell_grids = grid_strategy.get_active_sell_grids()
        assert len(sell_grids) == 1
        assert sell_grids[0].level == 3

    def test_mark_position_filled(self, grid_strategy):
        grid_strategy.mark_position_filled(2, 12345)
        assert grid_strategy.grids[2].position_filled is True
        assert grid_strategy.grids[2].buy_order_id == 12345

    def test_mark_position_closed(self, grid_strategy):
        grid_strategy.mark_position_filled(2, 12345)
        grid_strategy.mark_position_closed(2, 12346)
        assert grid_strategy.grids[2].position_filled is False
        assert grid_strategy.grids[2].sell_order_id == 12346

    def test_is_within_grid_range(self, grid_strategy):
        assert grid_strategy.is_within_grid_range(50000.0) is True
        assert grid_strategy.is_within_grid_range(45000.0) is True
        assert grid_strategy.is_within_grid_range(55000.0) is True
        assert grid_strategy.is_within_grid_range(44000.0) is False
        assert grid_strategy.is_within_grid_range(56000.0) is False

    def test_grid_status(self, grid_strategy):
        status = grid_strategy.grid_status
        assert status["total_grids"] == 10
        assert status["filled_positions"] == 0
        assert status["empty_positions"] == 10
        assert status["current_price"] == 50000.0

    def test_update_current_price(self, grid_strategy):
        grid_strategy.update_current_price(51000.0)
        assert grid_strategy.current_price == 51000.0

    def test_auto_range_is_15_percent(self):
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=100000.0,
            grid_count=10,
            investment_amount=1000.0,
        )
        assert strategy.lower_price == 85000.0
        assert abs(strategy.upper_price - 115000.0) < 0.01

    def test_profit_per_grid_percent(self, grid_strategy):
        pct = grid_strategy.profit_per_grid_percent
        assert pct > 0
