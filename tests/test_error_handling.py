"""例外ハンドリングとエラー回復のテスト"""

import time
from unittest.mock import MagicMock, patch

from src.bot import GridBot


def _make_bot():
    """テスト用のボットインスタンスを構築"""
    with patch.object(GridBot, "__init__", lambda self, *a, **kw: None):
        bot = GridBot.__new__(GridBot)
    bot.client = MagicMock()
    bot.client.get_symbol_price.return_value = 2300.0
    bot.client.get_symbol_info.return_value = {"symbol": "BTCUSDT"}
    bot.order_manager = MagicMock()
    bot.order_manager.check_order_fills.return_value = []
    bot.risk_manager = MagicMock()
    bot.risk_manager.should_halt_trading.return_value = False
    bot.portfolio = MagicMock()
    bot.portfolio.stats = MagicMock()
    bot.portfolio.stats.peak_balance = 0.0
    bot.portfolio.stats.max_drawdown_pct = 0.0
    bot.strategy = MagicMock()
    bot.strategy.current_price = 2300.0
    bot.strategy.is_within_grid_range.return_value = True
    bot.ws_client = None
    bot.symbol = "BTCUSDT"
    bot.is_running = True
    bot.consecutive_errors = 0
    bot._last_status_time = 0.0
    bot._last_persist_time = 0.0
    bot._last_detail_time = 0.0
    bot.current_price = 2300.0
    bot._close_open_positions = MagicMock()
    bot._persist_state = MagicMock()
    bot._handle_grid_shift = MagicMock()
    bot._price_history = [2300.0]
    bot._last_dynamic_factor = 0.15
    return bot


def test_tick_handles_api_exceptions_gracefully():
    """API例外時にconsecutive_errorsが増加する"""
    bot = _make_bot()
    bot.client.get_symbol_price.side_effect = ConnectionError("API connection failed")

    bot._tick()

    assert bot.consecutive_errors == 1


def test_tick_retries_on_max_errors():
    """連続エラーでもボットは停止せずリトライし続ける"""
    bot = _make_bot()
    bot.client.get_symbol_price.side_value = None
    bot.client.get_symbol_price.side_effect = ConnectionError("Fatal error")

    bot._tick()
    assert bot.consecutive_errors == 1
    assert bot.is_running is True  # 停止しない

    bot._tick()
    assert bot.consecutive_errors == 2
    assert bot.is_running is True  # まだ停止しない


def test_tick_resets_errors_on_success():
    """成功時にconsecutive_errorsがリセットされる"""
    bot = _make_bot()
    bot.consecutive_errors = 3
    bot._last_status_time = time.time() + 9999  # ステータス表示をスキップ
    bot._last_detail_time = time.time() + 9999
    bot._last_persist_time = time.time() + 9999

    bot._tick()

    assert bot.consecutive_errors == 0


def test_tick_halts_on_risk_manager():
    """リスク管理停止時にemergency_stopが呼ばれる"""
    bot = _make_bot()
    bot.risk_manager.should_halt_trading.return_value = True

    with patch.object(bot, "_emergency_stop") as mock_emergency:
        bot._tick()
        mock_emergency.assert_called_once()
