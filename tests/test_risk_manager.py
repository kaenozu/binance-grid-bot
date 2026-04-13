"""
ファイルパス: tests/test_risk_manager.py
概要: リスク管理ロジックのテスト
説明: 損切りチェック、ポジション制限、リスクステータスを検証
関連ファイル: src/risk_manager.py, tests/conftest.py
"""

import pytest
from unittest.mock import MagicMock
from src.risk_manager import RiskManager
from src.grid_strategy import GridStrategy


class TestRiskManager:
    """リスク管理のテスト"""

    @pytest.fixture
    def risk_manager(self, grid_strategy):
        mock_client = MagicMock()
        return RiskManager(mock_client, grid_strategy, entry_price=50000.0)

    def test_stop_loss_price(self, risk_manager):
        assert risk_manager.stop_loss_price == 47500.0

    def test_check_stop_loss_not_triggered(self, risk_manager):
        assert risk_manager.check_stop_loss(48000.0) is False
        assert risk_manager.check_stop_loss(47501.0) is False

    def test_check_stop_loss_triggered(self, risk_manager):
        assert risk_manager.check_stop_loss(47500.0) is True
        assert risk_manager.check_stop_loss(45000.0) is True

    def test_can_open_position(self, risk_manager):
        assert risk_manager.can_open_position() is True

    def test_can_open_position_at_limit(self, risk_manager):
        for _ in range(5):
            risk_manager.record_position_open()
        assert risk_manager.can_open_position() is False

    def test_can_open_position_below_limit(self, risk_manager):
        for _ in range(4):
            risk_manager.record_position_open()
        assert risk_manager.can_open_position() is True

    def test_record_position_open(self, risk_manager):
        risk_manager.record_position_open()
        assert risk_manager.current_positions == 1

    def test_record_position_close(self, risk_manager):
        risk_manager.record_position_open()
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=10.0)
        assert risk_manager.current_positions == 1
        assert risk_manager.total_trades == 1
        assert risk_manager.total_profit == 10.0

    def test_total_profit_accumulation(self, risk_manager):
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=5.0)
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=-2.0)
        assert risk_manager.total_profit == 3.0
        assert risk_manager.total_trades == 2

    def test_risk_status(self, risk_manager):
        status = risk_manager.get_risk_status()
        assert status["stop_loss_price"] == 47500.0
        assert status["current_positions"] == 0
        assert status["max_positions"] == 5
        assert status["total_trades"] == 0
        assert status["total_profit"] == 0.0
        assert status["stop_loss_percentage"] == 5.0

    def test_update_peak_and_drawdown(self, risk_manager):
        risk_manager.update_peak(10000.0)
        assert risk_manager.peak_value == 10000.0

        risk_manager.update_peak(10500.0)
        assert risk_manager.peak_value == 10500.0

        risk_manager.update_peak(10000.0)
        assert abs(risk_manager.max_drawdown - 4.761904761904762) < 0.001

    def test_should_halt_trading_stop_loss(self, risk_manager):
        assert risk_manager.should_halt_trading(47000.0) is True

    def test_should_halt_trading_safe(self, risk_manager):
        assert risk_manager.should_halt_trading(50000.0) is False

    def test_emergency_actions_empty(self, risk_manager):
        actions = risk_manager.get_emergency_actions()
        assert actions == []

    def test_emergency_actions_high_positions(self):
        mock_client = MagicMock()
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0,
        )
        rm = RiskManager(mock_client, strategy, entry_price=50000.0)
        for _ in range(5):
            rm.record_position_open()
        actions = rm.get_emergency_actions()
        assert len(actions) >= 1
