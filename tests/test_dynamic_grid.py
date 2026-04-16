"""動的グリッドのテスト"""

import pytest

from src.grid_strategy import GridStrategy
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
    strategy.mark_position_filled(5, 99999)
    new_price = BASE_PRICE + SPACING * 3
    strategy.update_current_price(new_price)
    strategy.shift_grids()
    range_factor = 0.08
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
