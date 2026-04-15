"""グリッド取引戦略のテスト"""

from src.grid_strategy import GridStrategy
from tests.conftest import BASE_PRICE, LOWER_PRICE, UPPER_PRICE

SPACING = (UPPER_PRICE - LOWER_PRICE) / 10  # 2220.0


class TestGridStrategy:
    """グリッド戦略のテスト"""

    def test_grid_initialization(self, grid_strategy):
        assert grid_strategy.symbol == "BTCUSDT"
        assert grid_strategy.lower_price == LOWER_PRICE
        assert grid_strategy.upper_price == UPPER_PRICE
        assert grid_strategy.grid_count == 10
        assert len(grid_strategy.grids) == 10

    def test_grid_spacing(self, grid_strategy):
        assert grid_strategy.grid_spacing == SPACING

    def test_grid_prices(self, grid_strategy):
        assert grid_strategy.grids[0].buy_price == LOWER_PRICE
        assert grid_strategy.grids[9].buy_price == LOWER_PRICE + SPACING * 9
        assert grid_strategy.grids[1].buy_price == LOWER_PRICE + SPACING

    def test_sell_prices(self, grid_strategy):
        assert grid_strategy.grids[0].sell_price == LOWER_PRICE + SPACING
        assert grid_strategy.grids[9].sell_price is None

    def test_order_quantity(self, grid_strategy):
        qty = grid_strategy.get_order_quantity(
            BASE_PRICE, min_qty=0.00001, step_size=0.00001
        )
        assert qty > 0

    def test_order_quantity_respects_min_qty(self, grid_strategy):
        qty = grid_strategy.get_order_quantity(BASE_PRICE, min_qty=0.001, step_size=0.00001)
        assert qty >= 0.001

    def test_active_buy_grids(self, grid_strategy):
        buy_grids = grid_strategy.get_active_buy_grids()
        assert len(buy_grids) == 6
        assert all(g.buy_price <= BASE_PRICE for g in buy_grids)

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
        assert grid_strategy.is_within_grid_range(BASE_PRICE) is True
        assert grid_strategy.is_within_grid_range(LOWER_PRICE) is True
        assert grid_strategy.is_within_grid_range(UPPER_PRICE) is True
        assert grid_strategy.is_within_grid_range(LOWER_PRICE - 1000) is False
        assert grid_strategy.is_within_grid_range(UPPER_PRICE + 1000) is False

    def test_grid_status(self, grid_strategy):
        status = grid_strategy.grid_status
        assert status["total_grids"] == 10
        assert status["filled_positions"] == 0
        assert status["empty_positions"] == 10
        assert status["current_price"] == BASE_PRICE

    def test_update_current_price(self, grid_strategy):
        grid_strategy.update_current_price(BASE_PRICE + 1000)
        assert grid_strategy.current_price == BASE_PRICE + 1000

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
