"""WebSocket クライアントのテスト"""

import json
import threading
import time
from unittest.mock import MagicMock

from src.ws_client import BinanceWebSocketClient
from tests.conftest import BASE_PRICE


class TestBinanceWebSocketClient:
    def test_initial_state(self):
        ws = BinanceWebSocketClient()
        assert ws.current_price is None
        assert ws._running is False

    def test_set_on_price_callback(self):
        ws = BinanceWebSocketClient()
        cb = MagicMock()
        ws.set_on_price(cb)
        assert ws._on_price is cb

    def test_on_ticker_message_updates_price(self):
        ws = BinanceWebSocketClient()
        message = json.dumps({"c": "74000.50", "s": "BTCUSDT"})
        ws._on_ticker_message(None, message)
        assert ws.current_price == 74000.50

    def test_on_ticker_message_calls_callback(self):
        ws = BinanceWebSocketClient()
        cb = MagicMock()
        ws.set_on_price(cb)
        message = json.dumps({"c": "74000.50"})
        ws._on_ticker_message(None, message)
        cb.assert_called_once_with(74000.50)

    def test_stop_sets_running_false(self):
        ws = BinanceWebSocketClient()
        ws._running = True
        ws._thread = MagicMock()
        ws._thread.is_alive.return_value = False
        ws.stop()
        assert ws._running is False

    def test_thread_safety_concurrent_price_access(self):
        ws = BinanceWebSocketClient()
        errors = []

        def writer():
            try:
                for i in range(100):
                    ws._on_ticker_message(
                        None, json.dumps({"c": str(BASE_PRICE + i)})
                    )
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    _ = ws.current_price
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
