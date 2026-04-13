"""
ファイルパス: tests/test_portfolio.py
概要: 資産管理・PnL計算のテスト
説明: 取引記録、損益計算、勝率計算を検証
関連ファイル: src/portfolio.py, tests/conftest.py
"""

import pytest
from src.portfolio import Portfolio, Trade, PortfolioStats


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
            price=50000.0,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        assert len(portfolio.trades) == 1
        assert portfolio.trades[0].side == "BUY"
        assert portfolio.trades[0].price == 50000.0
        assert portfolio.trades[0].quantity == 0.002
        assert portfolio.stats.total_trades == 1

    def test_record_sell_trade_with_profit(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=50000.0,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=51000.0,
            quantity=0.002,
            order_id=12346,
            grid_level=5,
        )
        assert portfolio.stats.realized_profit == 2.0
        assert portfolio.stats.winning_trades == 1
        assert portfolio.stats.losing_trades == 0

    def test_record_sell_trade_with_loss(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=50000.0,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=49000.0,
            quantity=0.002,
            order_id=12346,
            grid_level=5,
        )
        assert portfolio.stats.realized_profit == -2.0
        assert portfolio.stats.winning_trades == 0
        assert portfolio.stats.losing_trades == 1

    def test_win_rate_calculation(self, portfolio):
        for i in range(3):
            portfolio.record_trade(
                side="BUY",
                price=50000.0,
                quantity=0.002,
                order_id=12340 + i * 2,
                grid_level=i,
            )
            sell_price = 51000.0 if i < 2 else 49000.0
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
            price=50000.0,
            quantity=0.002,
            order_id=12345,
            grid_level=0,
        )
        portfolio.record_trade(
            side="SELL",
            price=51000.0,
            quantity=0.002,
            order_id=12346,
            grid_level=0,
        )
        assert portfolio.stats.settled_trades == 1
        assert abs(portfolio.stats.avg_profit_per_trade - 2.0) < 0.01

    def test_unrealized_pnl(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=50000.0,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.calculate_unrealized_pnl(51000.0)
        assert portfolio.stats.unrealized_profit == 2.0

    def test_unrealized_pnl_no_positions(self, portfolio):
        portfolio.calculate_unrealized_pnl(51000.0)
        assert portfolio.stats.unrealized_profit == 0.0

    def test_trade_history_limit(self, portfolio):
        for i in range(30):
            portfolio.record_trade(
                side="BUY",
                price=50000.0,
                quantity=0.002,
                order_id=12340 + i,
                grid_level=i % 10,
            )
        history = portfolio.get_trade_history(limit=20)
        assert len(history) == 20

    def test_find_matching_buy_trade(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=50000.0,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        buy_trade = portfolio.find_matching_buy_trade(5)
        assert buy_trade is not None
        assert buy_trade.price == 50000.0

    def test_find_matching_buy_trade_not_found(self, portfolio):
        assert portfolio.find_matching_buy_trade(99) is None

    def test_matched_flag_prevents_double_matching(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=50000.0,
            quantity=0.002,
            order_id=100,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=51000.0,
            quantity=0.002,
            order_id=101,
            grid_level=5,
        )
        portfolio.record_trade(
            side="BUY",
            price=49000.0,
            quantity=0.002,
            order_id=102,
            grid_level=5,
        )
        buy_trade = portfolio.find_matching_buy_trade(5)
        assert buy_trade is not None
        assert buy_trade.price == 49000.0

    def test_generate_report(self, portfolio):
        portfolio.record_trade(
            side="BUY",
            price=50000.0,
            quantity=0.002,
            order_id=12345,
            grid_level=5,
        )
        portfolio.record_trade(
            side="SELL",
            price=51000.0,
            quantity=0.002,
            order_id=12346,
            grid_level=5,
        )
        report = portfolio.generate_report()
        assert "ポートフォリオレポート" in report
        assert "10000.00" in report
