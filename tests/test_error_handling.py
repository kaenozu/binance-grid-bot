import pytest
from unittest.mock import MagicMock
from src.bot import GridBot

def test_tick_handles_api_exceptions_gracefully():
    # GridBotのインスタンスを生成
    bot = GridBot(symbol="BTCUSDT", ws_client=MagicMock())
    
    # モックの割り当て（__init__内で生成されるclientをモックに差し替え）
    bot.client = MagicMock()
    bot.order_manager = MagicMock()
    bot.risk_manager = MagicMock()
    bot.portfolio = MagicMock()
    bot.strategy = MagicMock()
    
    # _update_price が例外を投げるように設定
    bot._update_price = MagicMock(side_effect=ConnectionError("API connection failed"))
    
    # 連続エラー回数を設定
    bot.consecutive_errors = 0
    
    # _tick を実行（例外がキャッチされ、エラーカウントが増えることを確認）
    bot._tick()
    
    assert bot.consecutive_errors == 1

def test_tick_stops_on_max_errors():
    import src.bot
    # 設定をモック
    src.bot.Settings.MAX_CONSECUTIVE_ERRORS = 2
    
    bot = GridBot(symbol="BTCUSDT", ws_client=MagicMock())
    
    # モックの割り当て
    bot.client = MagicMock()
    bot.order_manager = MagicMock()
    bot.risk_manager = MagicMock()
    bot.portfolio = MagicMock()
    bot.strategy = MagicMock()
    
    bot._update_price = MagicMock(side_effect=ConnectionError("Fatal error"))
    bot.stop = MagicMock()
    
    # 2回実行して停止するか確認
    bot._tick()
    bot._tick()
    
    assert bot.consecutive_errors == 2
    bot.stop.assert_called_once()
