"""Binance WebSocket クライアント

ファイルの役割: リアルタイム価格ストリームの受信
なぜ存在するか: ポーリング 대신高速な価格更新を実現するため
関連ファイル: bot.py（メインループ）, binance_client.py（REST API）
"""

import json
import threading
import time
from typing import Callable

from utils.logger import setup_logger

logger = setup_logger("ws_client")


class BinanceWebSocketClient:
    """Binance WebSocket クライアント"""

    STREAM_BASE_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._on_price: Callable[[float], None] | None = None
        self._on_order_update: Callable[[dict], None] | None = None
        self._ws = None
        self._current_price: float | None = None
        self._price_lock = threading.Lock()
        self._symbol: str | None = None
        self._reconnect_delay = 1

    @property
    def current_price(self) -> float | None:
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
                    ws = websocket.WebSocketApp(
                        url,
                        on_message=self._on_ticker_message,
                        on_error=self._on_error,
                        on_close=lambda ws_app, close_code, msg: None,
                    )
                    self._ws = ws
                    ws.run_forever(ping_interval=20, ping_timeout=10)
                    self._reconnect_delay = 1
                except Exception as e:
                    logger.error(f"WebSocket エラー: {e}")
                finally:
                    self._ws = None
                if self._running:
                    logger.info("WebSocket 再接続中...")
                    time.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, 60)

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
