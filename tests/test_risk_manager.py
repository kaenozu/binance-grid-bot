"""リスク管理ロジックのテスト"""

from unittest.mock import MagicMock

import pytest

from src.risk_manager import RiskManager
from tests.conftest import BASE_PRICE, LOWER_PRICE

# 損切り価格: 62900 * 0.95 = 59755.0
STOP_LOSS = LOWER_PRICE * 0.95


class TestRiskManager:
    """リスク管理のテスト"""

    @pytest.fixture
    def risk_manager(self, grid_strategy):
        mock_client = MagicMock()
        return RiskManager(mock_client, grid_strategy)

    def test_stop_loss_price(self, risk_manager):
        assert risk_manager.stop_loss_price == STOP_LOSS

    def test_check_stop_loss_not_triggered(self, risk_manager):
        assert risk_manager.check_stop_loss(STOP_LOSS + 1.0) is False
        assert risk_manager.check_stop_loss(BASE_PRICE) is False

    def test_check_stop_loss_triggered(self, risk_manager):
        assert risk_manager.check_stop_loss(STOP_LOSS) is True
        assert risk_manager.check_stop_loss(STOP_LOSS - 1000) is True

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
        assert status["stop_loss_price"] == STOP_LOSS
        assert status["current_positions"] == 0
        assert status["max_positions"] == 5
        assert status["stop_loss_percentage"] == 5.0

    def test_should_halt_trading_stop_loss(self, risk_manager):
        assert risk_manager.should_halt_trading(STOP_LOSS - 1000) is True

    def test_should_halt_trading_safe(self, risk_manager):
        assert risk_manager.should_halt_trading(BASE_PRICE) is False
