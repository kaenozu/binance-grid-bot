from unittest.mock import MagicMock

from src.grid_strategy import GridStrategy
from src.risk_manager import RiskManager


def test_dynamic_grid_volatility():
    # GridStrategy の初期化
    strategy = GridStrategy(symbol="BTCUSDT", current_price=50000)

    # ATRを用いた範囲調整をテスト
    strategy.update_grid_range_by_volatility(current_atr=1000, multiplier=2.0)

    assert strategy.upper_price - strategy.lower_price == 2000
    assert strategy.lower_price == 49000
    assert strategy.upper_price == 51000

def test_trailing_stop_logic():
    client = MagicMock()
    strategy = MagicMock()
    strategy.lower_price = 40000

    risk_manager = RiskManager(client, strategy)

    # 初期ストップロス確認
    initial_sl = risk_manager.stop_loss_price

    # 価格上昇に伴いトレーリングストップ更新
    risk_manager.update_trailing_stop(current_price=50000, trailing_percent=2.0)

    assert risk_manager.stop_loss_price > initial_sl
    assert risk_manager.stop_loss_price == 49000
