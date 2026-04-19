"""WebSocket クライアントのテスト"""

import json
import threading
import time
from unittest.mock import MagicMock

from src.binance_client import BinanceAPIError
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

    def test_start_user_stream_disables_on_listen_key_410(self, monkeypatch):
        ws = BinanceWebSocketClient(binance_client=MagicMock())
        ws._binance_client.create_listen_key.side_effect = BinanceAPIError(
            "listenKey endpoint unavailable (410)",
            status_code=410,
            endpoint="/api/v3/userDataStream",
        )
        mock_logger = MagicMock()
        monkeypatch.setattr("src.ws_client.logger", mock_logger)

        started = []

        def fake_thread(*args, **kwargs):
            started.append(True)
            return MagicMock()

        monkeypatch.setattr("src.ws_client.threading.Thread", fake_thread)

        ws.start_user_stream()

        assert ws._user_stream_enabled is False
        assert started == []
        warning_messages = [call.args[0] for call in mock_logger.info.call_args_list]
        assert any("status=410" in message for message in warning_messages)
        assert any("endpoint=/api/v3/userDataStream" in message for message in warning_messages)

    def test_start_user_stream_skips_when_disabled_by_setting(self, monkeypatch):
        monkeypatch.setattr("src.ws_client.Settings.USE_USER_STREAM", False)
        ws = BinanceWebSocketClient(binance_client=MagicMock())

        started = []

        def fake_thread(*args, **kwargs):
            started.append(True)
            return MagicMock()

        monkeypatch.setattr("src.ws_client.threading.Thread", fake_thread)

        ws.start_user_stream()

        assert ws._user_stream_enabled is False
        assert started == []
