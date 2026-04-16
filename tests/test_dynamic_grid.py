"""動的グリッドのテスト"""

import pytest

from src.grid_strategy import GridStrategy
from src.risk_manager import RiskManager
from tests.conftest import BASE_PRICE, LOWER_PRICE, UPPER_PRICE

SPACING = (UPPER_PRICE - LOWER_PRICE) / 10  # 2220.0


@pytest.fixture
def strategy():
    return GridStrategy(
        symbol="BTCUSDT",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )


def test_shift_grids_manual(strategy):
    strategy.mark_position_filled(3, 12345)
    new_lower = LOWER_PRICE + SPACING * 3
    new_upper = UPPER_PRICE + SPACING * 3
    strategy.shift_grids(new_lower=new_lower, new_upper=new_upper)
    assert strategy.lower_price == new_lower
    assert strategy.upper_price == new_upper
    filled_grids = [g for g in strategy.grids if g.position_filled]
    assert len(filled_grids) == 1
    assert filled_grids[0].buy_order_id == 12345


def test_shift_grids_auto(strategy):
    from config.settings import Settings
    strategy.mark_position_filled(5, 99999)
    new_price = BASE_PRICE + SPACING * 3
    strategy.update_current_price(new_price)
    strategy.shift_grids()
    range_factor = Settings.GRID_RANGE_FACTOR
    assert abs(strategy.lower_price - new_price * (1 - range_factor)) < 0.01
    assert abs(strategy.upper_price - new_price * (1 + range_factor)) < 0.01
    filled_grids = [g for g in strategy.grids if g.position_filled]
    assert len(filled_grids) == 1
    assert filled_grids[0].buy_order_id == 99999


def test_shift_preserves_unfilled(strategy):
    strategy.shift_grids(
        new_lower=LOWER_PRICE + SPACING, new_upper=UPPER_PRICE + SPACING
    )
    assert strategy.grids[0].position_filled is False
    assert strategy.grids[9].position_filled is False


def test_shift_updates_spacing(strategy):
    wider_upper = UPPER_PRICE + SPACING * 5
    strategy.shift_grids(new_lower=LOWER_PRICE, new_upper=wider_upper)
    expected_spacing = (wider_upper - LOWER_PRICE) / 10
    assert abs(strategy.grid_spacing - expected_spacing) < 0.01


class TestAdaptiveGridAndTrailingStop:
    """適応的グリッド + トレーリングストップのテスト"""

    def test_update_grid_range_by_volatility(self):
        """ボラティリティに応じたグリッド範囲調整"""
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=40000.0,
            upper_price=60000.0,
            grid_count=10,
            investment_amount=10000.0,
        )
        # 約定済みポジションを設定
        strategy.grids[0].position_filled = True
        strategy.grids[0].buy_price = 40000.0

        # ATR=1000, multiplier=2.0 → range_width=2000
        strategy.update_grid_range_by_volatility(current_atr=1000.0, multiplier=2.0)

        assert strategy.lower_price == 49000.0  # 50000 - 1000
        assert strategy.upper_price == 51000.0  # 50000 + 1000
        # 約定済みポジションは維持
        assert any(g.position_filled for g in strategy.grids)

    def test_trailing_stop_updates_upward(self):
        """トレーリングストップが価格上昇時に上方更新"""
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        mock_strategy = MagicMock()
        mock_strategy.lower_price = 40000.0

        rm = RiskManager(mock_client, mock_strategy)
        initial_sl = rm.stop_loss_price  # 約 38000

        # 価格上昇
        rm.update_trailing_stop(current_price=50000.0, trailing_percent=2.0)
        assert rm.stop_loss_price == 49000.0  # 50000 * 0.98
        assert rm.stop_loss_price > initial_sl

    def test_trailing_stop_does_not_update_downward(self):
        """トレーリングストップは下落時に更新されない"""
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        mock_strategy = MagicMock()
        mock_strategy.lower_price = 40000.0

        rm = RiskManager(mock_client, mock_strategy)
        initial_sl = rm.stop_loss_price

        # 価格下落
        rm.update_trailing_stop(current_price=30000.0, trailing_percent=2.0)
        assert rm.stop_loss_price == initial_sl
