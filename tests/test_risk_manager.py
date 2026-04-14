"""
ファイルパス: tests/test_risk_manager.py
概要: リスク管理ロジックのテスト
説明: 損切りチェック、ポジション制限、リスクステータスを検証
関連ファイル: src/risk_manager.py, tests/conftest.py
"""

from unittest.mock import MagicMock

import pytest

from src.risk_manager import RiskManager


class TestRiskManager:
    """リスク管理のテスト"""

    @pytest.fixture
    def risk_manager(self, grid_strategy):
        mock_client = MagicMock()
        return RiskManager(mock_client, grid_strategy)

    def test_stop_loss_price(self, risk_manager):
        # 損切りは lower_price (45000) を基準に -5%
        assert risk_manager.stop_loss_price == 42750.0

    def test_check_stop_loss_not_triggered(self, risk_manager):
        assert risk_manager.check_stop_loss(43000.0) is False
        assert risk_manager.check_stop_loss(42751.0) is False

    def test_check_stop_loss_triggered(self, risk_manager):
        assert risk_manager.check_stop_loss(42750.0) is True
        assert risk_manager.check_stop_loss(40000.0) is True

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

    def test_risk_status(self, risk_manager):
        status = risk_manager.risk_status
        assert status["stop_loss_price"] == 42750.0
        assert status["current_positions"] == 0
        assert status["max_positions"] == 5
        assert status["stop_loss_percentage"] == 5.0

    def test_should_halt_trading_stop_loss(self, risk_manager):
        # 損切り価格 42750 を下回ったら停止
        assert risk_manager.should_halt_trading(42000.0) is True

    def test_should_halt_trading_safe(self, risk_manager):
        assert risk_manager.should_halt_trading(50000.0) is False
