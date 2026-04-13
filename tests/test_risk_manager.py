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
    def strategy(self):
        """テスト用グリッド戦略"""
        return GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )

    @pytest.fixture
    def risk_manager(self, strategy):
        """テスト用リスクマネージャー"""
        mock_client = MagicMock()
        return RiskManager(mock_client, strategy, entry_price=50000.0)

    def test_stop_loss_price(self, risk_manager):
        """損切り価格が正しく計算されるか"""
        # デフォルト5%
        assert risk_manager.stop_loss_price == 47500.0  # 50000 * 0.95

    def test_check_stop_loss_not_triggered(self, risk_manager):
        """損切りが発動しない場合"""
        assert risk_manager.check_stop_loss(48000.0) is False
        # 47500.0 は損切りライン「以下」なので発動する
        # 発動しないのはそれより上
        assert risk_manager.check_stop_loss(47501.0) is False

    def test_check_stop_loss_triggered(self, risk_manager):
        """損切りが発動する場合"""
        # 損切りラインちょうどでも発動
        assert risk_manager.check_stop_loss(47500.0) is True
        assert risk_manager.check_stop_loss(45000.0) is True

    def test_can_open_position(self, risk_manager):
        """ポジション開設可能か"""
        assert risk_manager.can_open_position() is True

    def test_can_open_position_at_limit(self, risk_manager):
        """最大ポジション数に達したら新規不可"""
        for _ in range(5):
            risk_manager.record_position_open()
        
        assert risk_manager.can_open_position() is False

    def test_can_open_position_below_limit(self, risk_manager):
        """最大ポジション数以下なら可能"""
        for _ in range(4):
            risk_manager.record_position_open()
        
        assert risk_manager.can_open_position() is True

    def test_record_position_open(self, risk_manager):
        """ポジション開設が正しく記録されるか"""
        risk_manager.record_position_open()
        assert risk_manager.current_positions == 1

    def test_record_position_close(self, risk_manager):
        """ポジション決済が正しく記録されるか"""
        risk_manager.record_position_open()
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=10.0)
        
        assert risk_manager.current_positions == 1
        assert risk_manager.total_trades == 1
        assert risk_manager.total_profit == 10.0

    def test_total_profit_accumulation(self, risk_manager):
        """利益が正しく累積されるか"""
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=5.0)
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=-2.0)
        
        assert risk_manager.total_profit == 3.0
        assert risk_manager.total_trades == 2

    def test_win_rate_calculation(self, risk_manager):
        """勝率が正しく計算されるか"""
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=5.0)  # 勝ち
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=-2.0)  # 負け
        risk_manager.record_position_open()
        risk_manager.record_position_close(profit=3.0)  # 勝ち
        
        assert risk_manager.total_trades == 3
        assert risk_manager.total_profit == 6.0
        # 勝率はPortfolio側で計算、RiskManagerは取引カウントのみ

    def test_risk_status(self, risk_manager):
        """リスクステータスが正しく返されるか"""
        status = risk_manager.get_risk_status()
        
        assert status["stop_loss_price"] == 47500.0
        assert status["current_positions"] == 0
        assert status["max_positions"] == 5
        assert status["total_trades"] == 0
        assert status["total_profit"] == 0.0
        assert status["stop_loss_percentage"] == 5.0

    def test_update_peak_and_drawdown(self, risk_manager):
        """ピーク値とドローダウンが正しく更新されるか"""
        risk_manager.update_peak(10000.0)
        assert risk_manager.peak_value == 10000.0
        
        risk_manager.update_peak(10500.0)
        assert risk_manager.peak_value == 10500.0
        
        risk_manager.update_peak(10000.0)
        # ドローダウン: (10500 - 10000) / 10500 * 100 = 4.76%
        assert abs(risk_manager.max_drawdown - 4.761904761904762) < 0.001

    def test_should_halt_trading_stop_loss(self, risk_manager):
        """損切りで取引停止すべきか"""
        assert risk_manager.should_halt_trading(47000.0) is True

    def test_should_halt_trading_safe(self, risk_manager):
        """安全な場合は継続"""
        assert risk_manager.should_halt_trading(50000.0) is False

    def test_emergency_actions_empty(self, risk_manager):
        """緊急アクションが空の場合"""
        actions = risk_manager.get_emergency_actions()
        assert actions == []

    def test_emergency_actions_high_positions(self):
        """ポジション数が多い場合に緊急アクションが返される"""
        mock_client = MagicMock()
        strategy = GridStrategy(
            symbol="BTCUSDT",
            current_price=50000.0,
            lower_price=45000.0,
            upper_price=55000.0,
            grid_count=10,
            investment_amount=1000.0
        )
        risk_manager = RiskManager(mock_client, strategy, entry_price=50000.0)
        
        # 5中5に到達（100%）
        for _ in range(5):
            risk_manager.record_position_open()
        
        actions = risk_manager.get_emergency_actions()
        assert len(actions) >= 1
