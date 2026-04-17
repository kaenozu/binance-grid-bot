"""Binance WebSocket クライアント

ファイルの役割: リアルタイム価格ストリームとユーザーデータストリームの受信
なぜ存在するか: ポーリングを減らし、約定をリアルタイム検知するため
関連ファイル: bot.py, binance_client.py（listenKey管理）, order_manager.py（約定処理）
"""

import json
import threading
import time
from typing import Callable

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("ws_client")

PRICE_STALE_TIMEOUT = 60
LISTEN_KEY_REFRESH_INTERVAL = 1800


class BinanceWebSocketClient:
    """Binance WebSocket クライアント（価格ストリーム + ユーザーデータストリーム）"""

    MAINNET_STREAM_URL = "wss://stream.binance.com:9443/ws"
    TESTNET_STREAM_URL = "wss://testnet.binance.vision/ws"

    def __init__(self, binance_client=None):
        self._running = False
        self._user_stream_enabled = Settings.USE_USER_STREAM
        self._price_thread: threading.Thread | None = None
        self._user_thread: threading.Thread | None = None
        self._listen_key_thread: threading.Thread | None = None
        self._on_price: Callable[[float], None] | None = None
        self._on_order_update: Callable[[dict], None] | None = None
        self._ws_price = None
        self._ws_user = None
        self._current_price: float | None = None
        self._last_price_time: float = 0.0
        self._price_lock = threading.Lock()
        self._symbol: str | None = None
        self._reconnect_delay = 1
        self._binance_client = binance_client
        self._listen_key: str | None = None
        self._listen_key_lock = threading.Lock()

    @property
    def _stream_base_url(self) -> str:
        return self.TESTNET_STREAM_URL if Settings.USE_TESTNET else self.MAINNET_STREAM_URL

    @property
    def current_price(self) -> float | None:
        with self._price_lock:
            return self._current_price

    @property
    def is_price_stale(self) -> bool:
        """価格更新が滞っていないかチェック"""
        with self._price_lock:
            if self._current_price is None:
                return False
            return (time.time() - self._last_price_time) > PRICE_STALE_TIMEOUT

    @property
    def seconds_since_last_price(self) -> float:
        """最後の価格更新からの経過秒数"""
        with self._price_lock:
            if self._last_price_time == 0:
                return 0.0
            return time.time() - self._last_price_time

    def set_on_price(self, callback: Callable[[float], None]):
        """価格更新コールバックを設定"""
        self._on_price = callback

    def set_on_order_update(self, callback: Callable[[dict], None]):
        """約定イベントコールバックを設定（ユーザーデータストリーム）"""
        self._on_order_update = callback

    # ── 価格ストリーム ────────────────────────────────────────────────

    def start_price_stream(self, symbol: str):
        """MiniTicker ストリームで価格をリアルタイム受信"""
        import websocket  # type: ignore[import-untyped]

        self._running = True
        self._symbol = symbol

        def _run():
            url = f"{self._stream_base_url}/{symbol.lower()}@miniTicker"
            while self._running:
                try:
                    ws = websocket.WebSocketApp(
                        url,
                        on_message=self._on_ticker_message,
                        on_error=self._on_price_error,
                        on_close=lambda ws_app, close_code, msg: None,
                    )
                    self._ws_price = ws
                    ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    logger.error(f"価格ストリーム WebSocket エラー: {e}")
                finally:
                    self._ws_price = None
                if self._running:
                    logger.info(f"価格ストリーム再接続中... ({self._reconnect_delay}秒後)")
                    time.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, 60)

        self._price_thread = threading.Thread(target=_run, daemon=True)
        self._price_thread.start()
        logger.info(f"価格ストリーム開始: {symbol}")

    def _on_ticker_message(self, ws, message):
        try:
            data = json.loads(message)
            price = float(data.get("c", 0))
            if price > 0:
                with self._price_lock:
                    self._current_price = price
                    self._last_price_time = time.time()
                self._reconnect_delay = 1
                if self._on_price:
                    self._on_price(price)
        except Exception as e:
            logger.error(f"ティッカー処理エラー: {e}")

    def _on_price_error(self, ws, error):
        logger.warning(f"価格ストリーム切断: {error}。自動再接続します")
        if ws:
            ws.close()

    # ── ユーザーデータストリーム（リアルタイム約定検知）───────────────

    def start_user_stream(self):
        """ユーザーデータストリームで約定イベントをリアルタイム受信

        listenKeyを作成し、30分ごとに自動延長する。
        ORDER_TRADE_UPDATE イベントをコールバックで通知する。
        """
        if not self._binance_client:
            logger.warning("binance_client が未設定。ユーザーストリームをスキップします")
            return
        if not self._user_stream_enabled:
            logger.info("ユーザーストリームは設定で無効化されています。listenKey は作成しません")
            return

        try:
            self._listen_key = self._binance_client.create_listen_key()
        except Exception as e:
            if self._is_unsupported_listen_key_error(e):
                self._disable_user_stream(self._describe_listen_key_error(e))
                return
            logger.error(f"listenKey 作成失敗: {e}。ユーザーストリームをスキップします")
            return

        self._running = True

        self._listen_key_thread = threading.Thread(target=self._keep_listen_key_alive, daemon=True)
        self._listen_key_thread.start()

        self._user_thread = threading.Thread(target=self._run_user_stream, daemon=True)
        self._user_thread.start()
        logger.info("ユーザーデータストリーム開始")

    def _run_user_stream(self):
        """ユーザーデータストリームの接続ループ"""
        import websocket  # type: ignore[import-untyped]

        reconnect_delay = 1
        while self._running:
            with self._listen_key_lock:
                key = self._listen_key
            if not key:
                logger.warning("listenKey なし。ユーザーストリーム終了")
                return

            url = f"{self._stream_base_url}/{key}"
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_user_message,
                    on_error=self._on_user_error,
                    on_close=lambda ws_app, close_code, msg: None,
                )
                self._ws_user = ws
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                logger.error(f"ユーザーストリーム WebSocket エラー: {e}")
            finally:
                self._ws_user = None

            if self._running:
                try:
                    if self._binance_client:
                        self._listen_key = self._binance_client.create_listen_key()
                        logger.info("ユーザーストリーム: listenKey 再作成完了")
                except Exception as e:
                    if self._is_unsupported_listen_key_error(e):
                        self._disable_user_stream(self._describe_listen_key_error(e))
                        return
                    logger.error(f"ユーザーストリーム: listenKey 再作成失敗: {e}")
                logger.info(f"ユーザーストリーム再接続中... ({reconnect_delay}秒後)")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    def _on_user_message(self, ws, message):
        """ユーザーデータストリームのメッセージを処理"""
        try:
            data = json.loads(message)
            event_type = data.get("e")

            if event_type == "ORDER_TRADE_UPDATE":
                order_data = data.get("o", {})
                if order_data.get("x") == "TRADE" and order_data.get("X") == "FILLED":
                    fill_info = {
                        "symbol": order_data.get("s"),
                        "side": order_data.get("S"),
                        "order_id": order_data.get("i"),
                        "price": float(order_data.get("p", 0)),
                        "quantity": float(order_data.get("q", 0)),
                        "commission": float(order_data.get("n", 0)),
                        "commission_asset": order_data.get("N", ""),
                        "trade_time": order_data.get("T"),
                    }
                    logger.info(
                        f"WS約定検知: {fill_info['side']} "
                        f"{fill_info['quantity']} {fill_info['symbol']} "
                        f"@ {fill_info['price']}"
                    )
                    if self._on_order_update:
                        self._on_order_update(fill_info)

            elif event_type == "listenKeyExpired":
                logger.warning("listenKey 期限切れ。再作成します")
                try:
                    if self._binance_client:
                        self._listen_key = self._binance_client.create_listen_key()
                except Exception as e:
                    if self._is_unsupported_listen_key_error(e):
                        self._disable_user_stream(self._describe_listen_key_error(e))
                        return
                    logger.error(f"listenKey 再作成失敗: {e}")

            elif event_type == "outboundAccountPosition":
                logger.debug("アカウント更新通知を受信")

        except Exception as e:
            logger.error(f"ユーザーストリームメッセージ処理エラー: {e}")

    def _on_user_error(self, ws, error):
        logger.warning(f"ユーザーストリーム切断: {error}。自動再接続します")
        if ws:
            ws.close()

    def _keep_listen_key_alive(self):
        """listenKey を定期的に延長（30分ごと）"""
        while self._running:
            time.sleep(LISTEN_KEY_REFRESH_INTERVAL)
            if not self._running:
                break
            with self._listen_key_lock:
                key = self._listen_key
            if not key:
                continue
            try:
                if self._binance_client:
                    self._binance_client.keepalive_listen_key(key)
                    logger.debug("listenKey 延長完了")
            except Exception as e:
                if self._is_unsupported_listen_key_error(e):
                    self._disable_user_stream(self._describe_listen_key_error(e))
                    return
                logger.warning(f"listenKey 延長失敗: {e}。再作成します")
                try:
                    if self._binance_client:
                        self._listen_key = self._binance_client.create_listen_key()
                        logger.info("listenKey 再作成完了")
                except Exception as e2:
                    if self._is_unsupported_listen_key_error(e2):
                        self._disable_user_stream(self._describe_listen_key_error(e2))
                        return
                    logger.error(f"listenKey 再作成失敗: {e2}")

    # ── 停止 ──────────────────────────────────────────────────────────

    def stop(self):
        """全ストリームを停止"""
        self._running = False
        for ws in (self._ws_price, self._ws_user):
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass
        for t in (self._price_thread, self._user_thread, self._listen_key_thread):
            if t and t.is_alive():
                t.join(timeout=5)
        if self._listen_key and self._binance_client:
            try:
                self._binance_client.close_listen_key(self._listen_key)
            except Exception:
                pass
        self._listen_key = None
        logger.info("WebSocket ストリーム停止")

    def _disable_user_stream(self, reason: str) -> None:
        """ユーザーストリームを無効化し、再試行を止める"""
        self._user_stream_enabled = False
        self._listen_key = None
        logger.warning(f"{reason}。ユーザーストリームを無効化してポーリングにフォールバックします")

    @staticmethod
    def _describe_listen_key_error(error: Exception) -> str:
        """listenKey エラーの詳細をログ向けに整形する"""
        status_code = getattr(error, "status_code", None)
        endpoint = getattr(error, "endpoint", None) or "unknown"
        return f"listenKey が利用できません (status={status_code}, endpoint={endpoint}, error={error})"

    @staticmethod
    def _is_unsupported_listen_key_error(error: Exception) -> bool:
        """listenKey エンドポイントが使えないケースを判定する"""
        status_code = getattr(error, "status_code", None)
        endpoint = getattr(error, "endpoint", "") or ""
        if status_code == 410 and endpoint.endswith("/userDataStream"):
            return True
        if status_code == 410 and "listenKey endpoint unavailable" in str(error):
            return True
        return False
