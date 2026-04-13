"""
ファイルパス: tests/test_grid_strategy.py
概要: グリッド取引戦略のテスト
説明: グリッド計算、注文数量、アクティブグリッドのロジックを検証
関連ファイル: src/grid_strategy.py, tests/conftest.py
"""

import pytest
from src.grid_strategy import GridStrategy, GridConfig


class TestGridStrategy:
    """グリッド戦略のテスト"""

    def test_grid_initialization(self):
        """グリッドが正しく初期化されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        assert strategy.symbol == "BTCUSDT"
        assert strategy.lower_price == 45000.0
        assert strategy.upper_price == 55000.0
        assert strategy.grid_count == 10
        assert len(strategy.grids) == 11  # grid_count + 1

    def test_grid_spacing(self):
        """グリッド間隔が正しく計算されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        expected_spacing = (55000.0 - 45000.0) / 10  # 1000.0
        assert strategy.config.grid_spacing == expected_spacing

    def test_grid_prices(self):
        """各グリッドの価格が正しく計算されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        # グリッド0: 下限価格
        assert strategy.grids[0].buy_price == 45000.0
        # グリッド10: 上限価格
        assert strategy.grids[10].buy_price == 55000.0
        # グリッド1: 下限 + 間隔
        assert strategy.grids[1].buy_price == 46000.0

    def test_sell_prices(self):
        """売り価格が正しく計算されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        # グリッド0の売り価格 = グリッド1の買い価格
        assert strategy.grids[0].sell_price == 46000.0
        # 最後のグリッドには売り価格がない
        assert strategy.grids[10].sell_price is None

    def test_order_quantity(self):
        """注文数量が正しく計算されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        # 1グリッドあたり: 1000 / 10 = 100 USDT
        # 数量: 100 / 50000 = 0.002
        qty = strategy.get_order_quantity(50000.0, min_qty=0.00001, step_size=0.00001)
        assert abs(qty - 0.002) < 0.00001

    def test_order_quantity_respects_min_qty(self):
        """注文数量が最小数量を下回らないか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        qty = strategy.get_order_quantity(50000.0, min_qty=0.001, step_size=0.00001)
        assert qty >= 0.001

    def test_active_buy_grids(self):
        """アクティブな買い注文グリッドが正しく取得されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        # 現在価格(50000)以下のグリッドがアクティブ
        buy_grids = strategy.get_active_buy_grids()
        assert len(buy_grids) == 6  # グリッド0〜5
        assert all(g.buy_price <= 50000.0 for g in buy_grids)

    def test_active_sell_grids(self):
        """アクティブな売り注文グリッドが正しく取得されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        # 最初はポジションなし
        sell_grids = strategy.get_active_sell_grids()
        assert len(sell_grids) == 0

        # ポジションを持たせる
        strategy.mark_position_filled(3, 12345)
        sell_grids = strategy.get_active_sell_grids()
        assert len(sell_grids) == 1
        assert sell_grids[0].level == 3

    def test_mark_position_filled(self):
        """ポジション持ちが正しく記録されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        strategy.mark_position_filled(2, 12345)
        assert strategy.grids[2].position_filled is True
        assert strategy.grids[2].buy_order_id == 12345

    def test_mark_position_closed(self):
        """ポジション解消が正しく記録されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        strategy.mark_position_filled(2, 12345)
        strategy.mark_position_closed(2, 12346)
        assert strategy.grids[2].position_filled is False
        assert strategy.grids[2].sell_order_id == 12346

    def test_calculate_realized_profit(self):
        """実現利益が正しく計算されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        profit = strategy.calculate_realized_profit(50000.0, 51000.0, 0.002)
        assert profit == 2.0  # (51000 - 50000) * 0.002

    def test_is_within_grid_range(self):
        """価格がグリッド範囲内か正しく判定されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        assert strategy.is_within_grid_range(50000.0) is True
        assert strategy.is_within_grid_range(45000.0) is True
        assert strategy.is_within_grid_range(55000.0) is True
        assert strategy.is_within_grid_range(44000.0) is False
        assert strategy.is_within_grid_range(56000.0) is False

    def test_grid_status(self):
        """グリッドステータスが正しく返されるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        status = strategy.get_grid_status()
        assert status["total_grids"] == 11
        assert status["filled_positions"] == 0
        assert status["empty_positions"] == 11
        assert status["current_price"] == 50000.0

    def test_update_current_price(self):
        """現在価格の更新が正しく行われるか"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

        strategy.update_current_price(51000.0)
        assert strategy.current_price == 51000.0
