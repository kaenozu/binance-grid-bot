"""
ファイルパス: src/ws_client.py
概要: Binance WebSocket クライアント
説明: リアルタイム価格・注文更新をWebSocketで受信
関連ファイル: src/binance_client.py, src/order_manager.py
"""

import json
import time
import threading
from typing import Optional, Callable

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

    @property
    def current_price(self) -> Optional[float]:
        return self._current_price

    def start_price_stream(self, symbol: str):
        """MiniTicker ストリームで価格をリアルタイム受信"""
        import websocket

        self._running = True

        def _run():
            url = f"{self.STREAM_BASE_URL}/{symbol.lower()}@miniTicker"
            while self._running:
                try:
                    ws = websocket.WebSocketApp()
                    ws.on_message = self._on_ticker_message
                    ws.on_error = self._on_error
                    ws.on_close = lambda ws_app, code, msg: (
                        self._schedule_reconnect(symbol) if self._running else None
                    )
                    ws.run_forever(url, ping_interval=20, ping_timeout=10)
                except Exception as e:
                    logger.error(f"WebSocket エラー: {e}")
                    if self._running:
                        time.sleep(5)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        logger.info(f"価格ストリーム開始: {symbol}")

    def _on_ticker_message(self, ws, message):
        try:
            data = json.loads(message)
            price = float(data.get("c", 0))
            if price > 0:
                self._current_price = price
                if self._on_price:
                    self._on_price(price)
        except Exception as e:
            logger.error(f"ティッカー処理エラー: {e}")

    def _schedule_reconnect(self, symbol: str):
        if self._running:
            logger.info("WebSocket 再接続中...")
            time.sleep(3)
            self.start_price_stream(symbol)

    def _on_error(self, ws, error):
        logger.error(f"WebSocket エラー: {error}")

    def stop(self):
        """ストリームを停止"""
        self._running = False
        logger.info("WebSocket ストリーム停止")
