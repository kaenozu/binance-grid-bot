"""
ファイルパス: src/ws_client.py
概要: Binance WebSocket クライアント
説明: リアルタイム価格・注文更新をWebSocketで受信。スレッドセーフ、単一ループ再接続。
関連ファイル: src/binance_client.py, src/bot.py, src/order_manager.py
"""

import json
import threading
import time
from typing import Callable, Optional

from utils.logger import setup_logger

logger = setup_logger("ws_client")


class BinanceWebSocketClient:
    """Binance WebSocket クライアント"""

    STREAM_BASE_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_price: Optional[Callable[[float], None]] = None
        self._on_order_update: Optional[Callable[[dict], None]] = None
        self._ws = None
        self._current_price: Optional[float] = None
        self._price_lock = threading.Lock()
        self._symbol: Optional[str] = None

    @property
    def current_price(self) -> Optional[float]:
        with self._price_lock:
            return self._current_price

    def set_on_price(self, callback: Callable[[float], None]):
        """価格更新コールバックを設定"""
        self._on_price = callback

    def start_price_stream(self, symbol: str):
        """MiniTicker ストリームで価格をリアルタイム受信"""
        import websocket  # type: ignore[import-untyped]

        self._running = True
        self._symbol = symbol

        def _run():
            url = f"{self.STREAM_BASE_URL}/{symbol.lower()}@miniTicker"
            while self._running:
                try:
                    ws = websocket.WebSocketApp()
                    ws.on_message = self._on_ticker_message
                    ws.on_error = self._on_error
                    ws.on_close = lambda ws_app, code, msg: None
                    self._ws = ws
                    ws.run_forever(url, ping_interval=20, ping_timeout=10)
                except Exception as e:
                    logger.error(f"WebSocket エラー: {e}")
                finally:
                    self._ws = None
                if self._running:
                    logger.info("WebSocket 再接続中...")
                    time.sleep(3)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        logger.info(f"価格ストリーム開始: {symbol}")

    def _on_ticker_message(self, ws, message):
        try:
            data = json.loads(message)
            price = float(data.get("c", 0))
            if price > 0:
                with self._price_lock:
                    self._current_price = price
                if self._on_price:
                    self._on_price(price)
        except Exception as e:
            logger.error(f"ティッカー処理エラー: {e}")

    def _on_error(self, ws, error):
        logger.error(f"WebSocket エラー: {error}")

    def stop(self):
        """ストリームを停止"""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("WebSocket ストリーム停止")
