"""
ファイルパス: tests/test_dynamic_grid.py
概要: 動的グリッドのテスト
説明: グリッドシフト機能を検証
関連ファイル: src/grid_strategy.py
"""

import pytest
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


def test_shift_grids_manual(strategy):
    strategy.mark_position_filled(3, 12345)
    strategy.shift_grids(new_lower=48000.0, new_upper=58000.0)
    assert strategy.lower_price == 48000.0
    assert strategy.upper_price == 58000.0
    assert strategy.grids[3].position_filled is True
    assert strategy.grids[3].buy_order_id == 12345


def test_shift_grids_auto(strategy):
    strategy.mark_position_filled(5, 99999)
    strategy.update_current_price(52000.0)
    strategy.shift_grids()
    range_factor = 0.15
    assert abs(strategy.lower_price - 52000.0 * (1 - range_factor)) < 0.01
    assert abs(strategy.upper_price - 52000.0 * (1 + range_factor)) < 0.01
    assert strategy.grids[5].position_filled is True


def test_shift_preserves_unfilled(strategy):
    strategy.shift_grids(new_lower=46000.0, new_upper=56000.0)
    assert strategy.grids[0].position_filled is False
    assert strategy.grids[9].position_filled is False


def test_shift_updates_spacing(strategy):
    strategy.shift_grids(new_lower=45000.0, new_upper=60000.0)
    expected_spacing = (60000.0 - 45000.0) / 10
    assert abs(strategy.grid_spacing - expected_spacing) < 0.01
