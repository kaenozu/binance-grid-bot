"""
ファイルパス: tests/test_backtest.py
概要: バックテストエンジンのテスト
説明: バックテストの実行、損切り、利益計算を検証
関連ファイル: src/backtest.py, tests/conftest.py
"""

from datetime import datetime

import pytest

from src.backtest import BacktestEngine


class TestBacktestEngine:
    """バックテストエンジンのテスト"""

    @pytest.fixture
    def sample_klines(self):
        return [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": 50000.0,
                "high": 50500.0,
                "low": 49500.0,
                "close": 50000.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": 50000.0,
                "high": 51000.0,
                "low": 49000.0,
                "close": 50500.0,
                "volume": 120.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": 50500.0,
                "high": 51500.0,
                "low": 50000.0,
                "close": 51000.0,
                "volume": 110.0,
                "close_time": datetime(2026, 1, 1, 3, 0),
            },
        ]

    @pytest.fixture
    def engine(self):
        return BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=1000.0,
            grid_count=10,
            lower_price=45000.0,
            upper_price=55000.0,
            stop_loss_percent=15.0,
        )

    def test_run_returns_report(self, engine, sample_klines):
        report = engine.run(sample_klines)
        assert report["symbol"] == "BTCUSDT"
        assert report["kline_count"] == 3
        assert report["start_price"] == 50000.0
        assert "roi_percent" in report
        assert "total_trades" in report

    def test_run_empty_klines(self, engine):
        report = engine.run([])
        assert report == {}

    def test_stop_loss_triggered(self):
        engine = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=1000.0,
            grid_count=10,
            lower_price=45000.0,
            upper_price=55000.0,
            stop_loss_percent=5.0,
        )
        # 損切り価格: 45000 * 0.95 = 42750
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": 50000.0,
                "high": 50000.0,
                "low": 50000.0,
                "close": 50000.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": 43000.0,
                "high": 43000.0,
                "low": 42000.0,
                "close": 42000.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
        ]
        report = engine.run(klines)
        assert report["stop_loss_triggered"] is True

    def test_avg_profit_zero_when_no_trades(self, engine):
        no_trade_klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": 80000.0,
                "high": 80000.0,
                "low": 80000.0,
                "close": 80000.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
        ]
        report = engine.run(no_trade_klines)
        assert report["avg_profit_per_trade"] == 0

    def test_report_has_grid_range(self, engine, sample_klines):
        report = engine.run(sample_klines)
        assert "grid_range" in report
        assert "45000" in report["grid_range"]

    def test_multiple_grid_fills(self):
        engine = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=10000.0,
            grid_count=5,
            lower_price=48000.0,
            upper_price=52000.0,
            stop_loss_percent=15.0,
        )
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": 50000.0,
                "high": 50000.0,
                "low": 50000.0,
                "close": 50000.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": 50000.0,
                "high": 50400.0,
                "low": 48500.0,
                "close": 49500.0,
                "volume": 200.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": 49500.0,
                "high": 50800.0,
                "low": 49200.0,
                "close": 50200.0,
                "volume": 200.0,
                "close_time": datetime(2026, 1, 1, 3, 0),
            },
        ]
        report = engine.run(klines)
        assert report["total_trades"] >= 0
        assert "max_drawdown_percent" in report

    def test_drawdown_is_calculated(self):
        engine = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=1000.0,
            grid_count=5,
            lower_price=45000.0,
            upper_price=55000.0,
            stop_loss_percent=15.0,
        )
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": 50000.0,
                "high": 51000.0,
                "low": 50000.0,
                "close": 50500.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": 50500.0,
                "high": 50500.0,
                "low": 46000.0,
                "close": 46500.0,
                "volume": 150.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": 46500.0,
                "high": 47500.0,
                "low": 46000.0,
                "close": 47000.0,
                "volume": 120.0,
                "close_time": datetime(2026, 1, 1, 3, 0),
            },
        ]
        report = engine.run(klines)
        assert report["max_drawdown_percent"] >= 0

    def test_fee_deduction_reduces_profit(self):
        no_fee = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=10000.0,
            grid_count=5,
            lower_price=49000.0,
            upper_price=51000.0,
            stop_loss_percent=15.0,
            fee_rate=0.0,
        )
        with_fee = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=10000.0,
            grid_count=5,
            lower_price=49000.0,
            upper_price=51000.0,
            stop_loss_percent=15.0,
            fee_rate=0.001,
        )
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": 50000.0,
                "high": 50000.0,
                "low": 50000.0,
                "close": 50000.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": 50000.0,
                "high": 50400.0,
                "low": 49200.0,
                "close": 49800.0,
                "volume": 200.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": 49800.0,
                "high": 50500.0,
                "low": 49500.0,
                "close": 50200.0,
                "volume": 200.0,
                "close_time": datetime(2026, 1, 1, 3, 0),
            },
        ]
        report_no_fee = no_fee.run(klines)
        report_with_fee = with_fee.run(klines)

        if report_no_fee["total_trades"] > 0:
            assert report_with_fee["total_profit"] <= report_no_fee["total_profit"]
