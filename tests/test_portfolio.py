"""資産管理・PnL計算のテスト"""

import pytest

from src.portfolio import Portfolio
from tests.conftest import BASE_PRICE

GRID_SPACING = 2220.0  # 本番相当のグリッド間隔


class TestPortfolio:
    """資産管理のテスト"""

    @pytest.fixture
    def portfolio(self, mock_client_for_portfolio):
        return Portfolio(mock_client_for_portfolio, "BTCUSDT", "USDT")

    def test_initial_balance(self, portfolio):
        assert portfolio.stats.initial_balance == 10000.0
        assert portfolio.stats.current_balance == 10000.0

    def test_record_buy_trade(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        assert len(portfolio.trades) == 1
        assert portfolio.trades[0].side == "BUY"
        assert portfolio.trades[0].price == BASE_PRICE
        assert portfolio.trades[0].quantity == 0.002
        assert portfolio.stats.total_trades == 1

    def test_record_sell_trade_with_profit(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=BASE_PRICE + GRID_SPACING,
            quantity=0.002,
            order_id=12346,
            grid_level=5,
        )
        expected_profit = GRID_SPACING * 0.002
        assert portfolio.stats.realized_profit == expected_profit
        assert portfolio.stats.winning_trades == 1
        assert portfolio.stats.losing_trades == 0

    def test_record_sell_trade_with_loss(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=BASE_PRICE - 500,
            quantity=0.002,
            order_id=12346,
            grid_level=5,
        )
        expected_profit = -500 * 0.002
        assert portfolio.stats.realized_profit == expected_profit
        assert portfolio.stats.winning_trades == 0
        assert portfolio.stats.losing_trades == 1

    def test_win_rate_calculation(self, portfolio):
        for i in range(3):
            portfolio.record_trade(
                side="BUY",
                price=BASE_PRICE,
                quantity=0.002,
                order_id=12340 + i * 2,
                grid_level=i,
            )
            sell_price = (BASE_PRICE + GRID_SPACING) if i < 2 else (BASE_PRICE - 500)
            portfolio.record_trade(
                side="SELL",
                price=sell_price,
                quantity=0.002,
                order_id=12341 + i * 2,
                grid_level=i,
            )
        assert portfolio.stats.winning_trades == 2
        assert portfolio.stats.losing_trades == 1
        assert abs(portfolio.stats.win_rate - 66.66666666666666) < 0.01

    def test_avg_profit_per_trade_uses_settled_count(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=0,
        )
        portfolio.record_trade(
            side="SELL",
            price=BASE_PRICE + GRID_SPACING,
            quantity=0.002,
            order_id=12346,
            grid_level=0,
        )
        assert portfolio.stats.settled_trades == 1
        expected_avg = GRID_SPACING * 0.002
        assert abs(portfolio.stats.avg_profit_per_trade - expected_avg) < 0.01

    def test_unrealized_pnl(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.calculate_unrealized_pnl(BASE_PRICE + 1000)
        assert portfolio.stats.unrealized_profit == 1000 * 0.002

    def test_unrealized_pnl_no_positions(self, portfolio):
        portfolio.calculate_unrealized_pnl(BASE_PRICE + 1000)
        assert portfolio.stats.unrealized_profit == 0.0

    def test_trade_history_limit(self, portfolio):
        for i in range(30):
            portfolio.record_trade(
                side="BUY",
                price=BASE_PRICE,
                quantity=0.002,
                order_id=12340 + i,
                grid_level=i % 10,
            )
        history = portfolio.get_trade_history(limit=20)
        assert len(history) == 20

    def test_find_matching_buy_trade(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        buy_trade = portfolio.find_matching_buy_trade(5)
        assert buy_trade is not None
        assert buy_trade.price == BASE_PRICE

    def test_find_matching_buy_trade_not_found(self, portfolio):
        assert portfolio.find_matching_buy_trade(99) is None

    def test_matched_flag_prevents_double_matching(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=100,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=BASE_PRICE + GRID_SPACING,
            quantity=0.002,
            order_id=101,
            grid_level=5,
        )
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE - GRID_SPACING,
            quantity=0.002,
            order_id=102,
            grid_level=5,
        )
        buy_trade = portfolio.find_matching_buy_trade(5)
        assert buy_trade is not None
        assert buy_trade.price == BASE_PRICE - GRID_SPACING

    def test_record_sell_trade_with_fee(self, mock_client_for_portfolio):
        fee_rate = 0.001
        portfolio = Portfolio(mock_client_for_portfolio, "BTCUSDT", "USDT", fee_rate=fee_rate)
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=BASE_PRICE + GRID_SPACING,
            quantity=0.002,
            order_id=12346,
            grid_level=5,
        )
        buy_fee = BASE_PRICE * 0.002 * fee_rate
        sell_fee = (BASE_PRICE + GRID_SPACING) * 0.002 * fee_rate
        gross_profit = GRID_SPACING * 0.002
        expected_profit = gross_profit - buy_fee - sell_fee
        expected_fees = buy_fee + sell_fee
        assert abs(portfolio.stats.realized_profit - expected_profit) < 0.01
        assert abs(portfolio.stats.total_fees - expected_fees) < 0.001

    def test_generate_report(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=BASE_PRICE + GRID_SPACING,
            quantity=0.002,
            order_id=12346,
            grid_level=5,
        )
        report = portfolio.generate_report()
        assert "ポートフォリオレポート" in report
        assert "10000.00" in report

    def test_calculate_unrealized_pnl_with_multiple_positions(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=0,
        )
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE + GRID_SPACING,
            quantity=0.002,
            order_id=12346,
            grid_level=1,
        )
        portfolio.calculate_unrealized_pnl(BASE_PRICE + GRID_SPACING * 2)
        total_unrealized = (GRID_SPACING * 2) * 0.002 + (GRID_SPACING) * 0.002
        assert abs(portfolio.stats.unrealized_profit - total_unrealized) < 0.01

    def test_refresh_stats(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=BASE_PRICE,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        stats = portfolio.refresh_stats()
        assert stats.total_trades == 1
        assert stats.current_balance == 10000.0

    def test_get_trade_history_all(self, portfolio):
        for i in range(5):
            portfolio.record_trade(
                side="BUY",
                price=BASE_PRICE,
                quantity=0.002,
                order_id=12340 + i,
                grid_level=i,
            )
        history = portfolio.get_trade_history()
        assert len(history) == 5

    def test_max_drawdown_tracked(self, portfolio):
        """最大ドローダウンが正しく追跡される"""
        portfolio.record_trade("BUY", 100.0, 0.1, 1, 0)
        portfolio.record_trade("SELL", 105.0, 0.1, 2, 0)
        portfolio.record_trade("BUY", 106.0, 0.1, 3, 1)
        portfolio.record_trade("SELL", 101.0, 0.1, 4, 1)
        portfolio.calculate_unrealized_pnl(100.0)
        assert portfolio.stats.peak_balance > 0
        assert portfolio.stats.max_drawdown >= 0

    def test_monthly_yearly_profit_tracked(self, portfolio):
        """月次/年次利益が正しく追跡される"""
        portfolio.record_trade("BUY", 100.0, 0.1, 1, 0)
        portfolio.record_trade("SELL", 105.0, 0.1, 2, 0)
        assert len(portfolio.stats.monthly_profit) > 0
        assert len(portfolio.stats.yearly_profit) > 0

    def test_sharpe_ratio_zero_without_trades(self, portfolio):
        """約定なしではシャープレシオが0"""
        portfolio.calculate_unrealized_pnl(BASE_PRICE)
        assert portfolio.stats.sharpe_ratio == 0.0

    def test_peak_balance_starts_at_zero(self, portfolio):
        """初期ピーク残高は0"""
        assert portfolio.stats.peak_balance == 0.0
        assert portfolio.stats.max_drawdown == 0.0
        assert portfolio.stats.max_drawdown_pct == 0.0
