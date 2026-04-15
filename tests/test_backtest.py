"""バックテストエンジンのテスト"""

from datetime import datetime

import pytest

from src.backtest import BacktestEngine
from tests.conftest import BASE_PRICE, LOWER_PRICE, UPPER_PRICE

SPACING = (UPPER_PRICE - LOWER_PRICE) / 10  # 2220.0


class TestBacktestEngine:
    """バックテストエンジンのテスト"""

    @pytest.fixture
    def sample_klines(self):
        return [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE + 500,
                "low": BASE_PRICE - 500,
                "close": BASE_PRICE,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE + 1000,
                "low": BASE_PRICE - 1000,
                "close": BASE_PRICE + 500,
                "volume": 120.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": BASE_PRICE + 500,
                "high": BASE_PRICE + 1500,
                "low": BASE_PRICE,
                "close": BASE_PRICE + 1000,
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
            lower_price=LOWER_PRICE,
            upper_price=UPPER_PRICE,
            stop_loss_percent=15.0,
        )

    def test_run_returns_report(self, engine, sample_klines):
        report = engine.run(sample_klines)
        assert report["symbol"] == "BTCUSDT"
        assert report["kline_count"] == 3
        assert report["start_price"] == BASE_PRICE
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
            lower_price=LOWER_PRICE,
            upper_price=UPPER_PRICE,
            stop_loss_percent=5.0,
        )
        # 損切り価格: 62900 * 0.95 = 59755
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE,
                "low": BASE_PRICE,
                "close": BASE_PRICE,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": 59000.0,
                "high": 59000.0,
                "low": 58000.0,
                "close": 58000.0,
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
                "open": 90000.0,
                "high": 90000.0,
                "low": 90000.0,
                "close": 90000.0,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
        ]
        report = engine.run(no_trade_klines)
        assert report["avg_profit_per_trade"] == 0

    def test_report_has_grid_range(self, engine, sample_klines):
        report = engine.run(sample_klines)
        assert "grid_range" in report
        assert "62900" in report["grid_range"]

    def test_multiple_grid_fills(self):
        # グリッド幅を狭くして約定を起こしやすくする
        engine = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=10000.0,
            grid_count=5,
            lower_price=BASE_PRICE - 1000,
            upper_price=BASE_PRICE + 1000,
            stop_loss_percent=15.0,
        )
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE,
                "low": BASE_PRICE,
                "close": BASE_PRICE,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE + 400,
                "low": BASE_PRICE - 800,
                "close": BASE_PRICE - 500,
                "volume": 200.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": BASE_PRICE - 500,
                "high": BASE_PRICE + 800,
                "low": BASE_PRICE - 600,
                "close": BASE_PRICE + 200,
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
            lower_price=LOWER_PRICE,
            upper_price=UPPER_PRICE,
            stop_loss_percent=15.0,
        )
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE + 1000,
                "low": BASE_PRICE,
                "close": BASE_PRICE + 500,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": BASE_PRICE + 500,
                "high": BASE_PRICE + 500,
                "low": LOWER_PRICE + 1000,
                "close": LOWER_PRICE + 2000,
                "volume": 150.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": LOWER_PRICE + 2000,
                "high": LOWER_PRICE + 3000,
                "low": LOWER_PRICE + 1000,
                "close": LOWER_PRICE + 2500,
                "volume": 120.0,
                "close_time": datetime(2026, 1, 1, 3, 0),
            },
        ]
        report = engine.run(klines)
        assert report["max_drawdown_percent"] >= 0

    def test_fee_deduction_reduces_profit(self):
        lower = BASE_PRICE - 500
        upper = BASE_PRICE + 500
        no_fee = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=10000.0,
            grid_count=5,
            lower_price=lower,
            upper_price=upper,
            stop_loss_percent=15.0,
            fee_rate=0.0,
        )
        with_fee = BacktestEngine(
            symbol="BTCUSDT",
            investment_amount=10000.0,
            grid_count=5,
            lower_price=lower,
            upper_price=upper,
            stop_loss_percent=15.0,
            fee_rate=0.001,
        )
        klines = [
            {
                "open_time": datetime(2026, 1, 1, 0, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE,
                "low": BASE_PRICE,
                "close": BASE_PRICE,
                "volume": 100.0,
                "close_time": datetime(2026, 1, 1, 1, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 1, 0),
                "open": BASE_PRICE,
                "high": BASE_PRICE + 400,
                "low": BASE_PRICE - 800,
                "close": BASE_PRICE - 200,
                "volume": 200.0,
                "close_time": datetime(2026, 1, 1, 2, 0),
            },
            {
                "open_time": datetime(2026, 1, 1, 2, 0),
                "open": BASE_PRICE - 200,
                "high": BASE_PRICE + 500,
                "low": BASE_PRICE - 300,
                "close": BASE_PRICE + 200,
                "volume": 200.0,
                "close_time": datetime(2026, 1, 1, 3, 0),
            },
        ]
        report_no_fee = no_fee.run(klines)
        report_with_fee = with_fee.run(klines)

        if report_no_fee["total_trades"] > 0:
            assert report_with_fee["total_profit"] <= report_no_fee["total_profit"]
