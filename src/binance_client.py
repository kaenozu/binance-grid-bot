"""Binance API クライアント

ファイルの役割: Binance APIへの注文・残高・価格取得等功能を提供
なぜ存在するか: 取引所との通信を抽象化するため
関連ファイル: bot.py（メインループ）, settings.py（設定）, api_weight.py（レート制限）
"""

import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import Settings
from src.api_weight import APIWeightTracker
from utils.logger import setup_logger
from utils.precision import format_decimal, get_precision, quantize_down, quantize_up

logger = setup_logger("binance_client")

RETRY_DELAY = 1
MAX_CONNECTION_RETRIES = 10
SYMBOL_CACHE_TTL = 300  # シンボル情報のキャッシュ有効期限（秒）


class BinanceAPIError(Exception):
    """Binance API 関連のエラー"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        endpoint: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint


class BinanceClient:
    """Binance API クライアント"""

    TESTNET_BASE_URL = "https://testnet.binance.vision"
    MAINNET_BASE_URL = "https://api.binance.com"

    def __init__(self, weight_tracker: APIWeightTracker | None = None):
        self.base_url = self.TESTNET_BASE_URL if Settings.USE_TESTNET else self.MAINNET_BASE_URL
        self.api_key = Settings.BINANCE_API_KEY
        self.api_secret = Settings.BINANCE_API_SECRET
        self._symbol_cache: dict[str, tuple[dict, float]] = {}
        self._weight_tracker = weight_tracker
        self._time_offset_ms = 0

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/json",
            }
        )
        # urllib3 の内部リトライを無効化（我々のリトライループに制御を委譲）
        self.session.mount(
            "https://",
            HTTPAdapter(max_retries=Retry(total=0, connect=0, read=0, redirect=0)),
        )

        self._sync_server_time()
        self._check_time_offset()

        logger.info(f"Binance クライアント初期化完了 (Testnet: {Settings.USE_TESTNET})")

    def close(self):
        """セッションをクローズ（リソース解放）"""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ── 署名・リクエスト ──────────────────────────────────────────────

    def _generate_signature(self, query_string: str) -> str:
        """署名を生成"""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _sign_params(self, params: dict) -> None:
        """params をインプレースで署名（timestamp と signature を付加）"""
        params.pop("signature", None)
        params["timestamp"] = self._current_timestamp_ms()
        query_string = urlencode(params)
        params["signature"] = self._generate_signature(query_string)

    def _current_timestamp_ms(self) -> int:
        """サーバー時刻との差分を反映したタイムスタンプを返す"""
        return int(time.time() * 1000) + self._time_offset_ms

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        signed: bool = False,
    ) -> dict:
        """API リクエストを実行（リトライ付き）"""
        url = f"{self.base_url}{endpoint}"
        params = dict(params) if params else {}

        if self._weight_tracker:
            self._weight_tracker.wait_if_needed()

        attempt = 0
        while True:
            attempt += 1
            if signed:
                self._sign_params(params)

            try:
                response = self._send_request(method, url, params)
            except requests.exceptions.ConnectionError as e:
                cause_str = str(e.__cause__) if e.__cause__ else str(e)
                is_dns = "NameResolutionError" in cause_str or "getaddrinfo failed" in cause_str
                tag = "DNS解決" if is_dns else "接続"
                if not self._can_retry(attempt, f"{tag}エラー"):
                    raise BinanceAPIError(
                        f"{tag}エラー（{MAX_CONNECTION_RETRIES}回リトライ後）: {e}"
                    ) from e
                wait = self._backoff(attempt)
                logger.warning(f"{tag}エラー、{wait}秒後にリトライ ({attempt}回目): {e}")
                time.sleep(wait)
                continue

            # ── 再試行不要なレスポンス ──
            if response.status_code < 400:
                self._update_weight(response)
                return response.json()

            if response.status_code == 429:
                if not self._can_retry(
                    attempt, f"レートリミット（{MAX_CONNECTION_RETRIES}回リトライ後）"
                ):
                    raise BinanceAPIError(f"レートリミット（{MAX_CONNECTION_RETRIES}回リトライ後）")
                retry_after = int(response.headers.get("Retry-After", RETRY_DELAY * (2**attempt)))
                logger.warning(f"レートリミット到達、{retry_after}秒後にリトライ ({attempt}回目)")
                time.sleep(retry_after)
                continue

            if response.status_code >= 500:
                if not self._can_retry(attempt, f"サーバーエラー ({response.status_code})"):
                    raise BinanceAPIError(
                        f"サーバーエラー ({response.status_code}) "
                        f"（{MAX_CONNECTION_RETRIES}回リトライ後）"
                    )
                wait = self._backoff(attempt)
                logger.warning(f"サーバーエラー ({response.status_code})、{wait}秒後にリトライ")
                time.sleep(wait)
                continue

            if response.status_code == 410 and endpoint.endswith("/userDataStream"):
                body = (response.text or "").strip() or "<empty>"
                logger.warning(
                    f"listenKey endpoint が 410 を返しました。endpoint={endpoint}, body={body}"
                )
                raise BinanceAPIError(
                    "listenKey endpoint unavailable (410)",
                    status_code=410,
                    endpoint=endpoint,
                )

            if signed and response.status_code == 400 and self._is_timestamp_error(response):
                if not self._can_retry(attempt, "timestampエラー"):
                    raise BinanceAPIError("timestampエラー（再同期後も失敗）")
                logger.warning("timestampズレを検知。サーバー時刻を再同期して再試行します")
                self._sync_server_time()
                time.sleep(self._backoff(attempt))
                continue

            # 4xx ── リトライしない（クライアントエラー）
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                body = e.response.text if e.response else ""
                status = getattr(e.response, "status_code", 0)
                safe_params = {
                    k: ("***MASKED***" if k == "signature" else v) for k, v in params.items()
                }
                logger.error(
                    f"4xxエラー ({status}): {body} | "
                    f"method={method} endpoint={endpoint} params={safe_params}"
                )
                raise BinanceAPIError(
                    f"クライアントエラー: {status} - {body}",
                    status_code=status,
                    endpoint=endpoint,
                ) from e

            # raise_for_status が通った（到達不能だが型チェッカー対策）
            return response.json()

    def _update_weight(self, response: requests.Response) -> None:
        """X-MBX-USED-WEIGHT ヘッダーからウェイトを更新"""
        if not self._weight_tracker:
            return
        used = response.headers.get("X-MBX-USED-WEIGHT")
        if used:
            self._weight_tracker.update_weight(int(used))

    @staticmethod
    def _can_retry(attempt: int, msg: str) -> bool:
        return attempt < MAX_CONNECTION_RETRIES

    @staticmethod
    def _backoff(attempt: int, cap: float = 60.0) -> float:
        return min(RETRY_DELAY * (2 ** min(attempt, 5)), cap)

    def _sync_server_time(self) -> None:
        """Binance サーバー時刻との差分を補正する"""
        try:
            url = f"{self.base_url}/api/v3/time"
            response = self._send_request("GET", url, {})
            if response.status_code != 200:
                logger.warning(f"サーバー時刻取得失敗: HTTP {response.status_code}")
                return
            server_time = response.json().get("serverTime")
            if not server_time:
                logger.warning("サーバー時刻レスポンスに serverTime がありません")
                return
            local_time = int(time.time() * 1000)
            self._time_offset_ms = int(server_time) - local_time
            logger.info(f"サーバー時刻を同期: offset={self._time_offset_ms}ms")
        except Exception as e:
            logger.warning(f"サーバー時刻同期失敗: {e}")

    @staticmethod
    def _is_timestamp_error(response: requests.Response) -> bool:
        """-1021 系の時刻ズレエラーか判定する"""
        body_text = response.text or ""
        if "-1021" in body_text or "timestamp" in body_text.lower():
            return True
        try:
            payload = response.json()
        except Exception:
            return False
        if isinstance(payload, dict):
            code = payload.get("code")
            message = str(payload.get("msg", ""))
            return code == -1021 or "timestamp" in message.lower()
        return False

    def _send_request(self, method: str, url: str, params: dict) -> requests.Response:
        """HTTP リクエストを送信（リトライなしの単発リクエスト）"""
        try:
            if method == "GET":
                return self.session.get(url, params=params, timeout=10)
            if method == "POST":
                return self.session.post(url, data=params, timeout=10)
            if method == "DELETE":
                return self.session.delete(url, params=params, timeout=10)
            raise ValueError(f"サポートされていない HTTP メソッド: {method}")
        except requests.exceptions.ConnectionError:
            raise  # _make_request 側で catch してリトライ
        except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            raise BinanceAPIError(f"リクエストエラー: {e}") from e

    def _check_time_offset(self) -> None:
        """時刻差分が許容範囲内かチェック（起動時）"""
        abs_offset = abs(self._time_offset_ms)
        if abs_offset > 5000:
            logger.warning(
                f"サーバー時刻との差分が大きいです: {self._time_offset_ms}ms. "
                "注文がリジェクトされる可能性があります。"
            )
        else:
            logger.info(f"時刻差分チェック OK: {self._time_offset_ms}ms")

    def _validate_order_request(
        self, symbol: str, side: str, quantity: float, price: float | None, symbol_info: dict | None
    ) -> tuple[float, float | None]:
        """Binance の制約に合わせて注文パラメータを事前検証する"""
        if quantity <= 0:
            raise BinanceAPIError(f"{side} 注文の数量が0以下です")

        if not symbol_info:
            return quantity, price

        step_size = float(symbol_info.get("step_size", 0) or 0)
        min_qty = float(symbol_info.get("min_qty", 0) or 0)
        max_qty = float(symbol_info.get("max_qty", 0) or 0)
        tick_size = float(symbol_info.get("tick_size", 0) or 0)
        min_notional = float(symbol_info.get("min_notional", 0) or 0)

        normalized_qty = quantize_down(quantity, step_size) if step_size > 0 else quantity
        if min_qty > 0 and normalized_qty < min_qty:
            normalized_qty = quantize_up(min_qty, step_size) if step_size > 0 else min_qty
        if max_qty > 0 and normalized_qty > max_qty:
            raise BinanceAPIError(
                f"{side} 注文の数量が最大数量を上回っています: {normalized_qty} > {max_qty}"
            )

        normalized_price = price
        if price is not None and tick_size > 0:
            rounding = "down" if side == "BUY" else "up"
            if rounding == "down":
                normalized_price = quantize_down(price, tick_size)
            else:
                normalized_price = quantize_up(price, tick_size)

        if price is not None and min_notional > 0:
            normalized_price_val = normalized_price if normalized_price is not None else price
            notional = normalized_qty * normalized_price_val
            if notional < min_notional:
                if price is None or normalized_price_val <= 0:
                    raise BinanceAPIError(
                        f"{side} 注文の額が最小名目金額を下回っています: "
                        f"{notional:.8f} < {min_notional}"
                    )
                needed_qty = (
                    quantize_up(min_notional / normalized_price_val, step_size)
                    if step_size > 0
                    else (min_notional / normalized_price_val)
                )
                if max_qty > 0 and needed_qty > max_qty:
                    raise BinanceAPIError(
                        f"{side} 注文の数量が最大数量を上回っています: {needed_qty} > {max_qty}"
                    )
                normalized_qty = needed_qty
                notional = normalized_qty * normalized_price_val
                if notional < min_notional:
                    raise BinanceAPIError(
                        f"{side} 注文の額が最小名目金額を下回っています: "
                        f"{notional:.8f} < {min_notional}"
                    )

        return normalized_qty, normalized_price

    # ── 公開 API ──────────────────────────────────────────────────────

    def get_account_balance(self) -> dict:
        """アカウント残高を取得"""
        data = self._make_request("GET", "/api/v3/account", signed=True)
        balances = {}
        for balance in data.get("balances", []):
            asset = balance["asset"]
            free = float(balance["free"])
            locked = float(balance["locked"])
            if free > 0 or locked > 0:
                balances[asset] = {"free": free, "locked": locked}
        return balances

    def get_symbol_price(self, symbol: str) -> float:
        """現在の価格を取得"""
        data = self._make_request("GET", "/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    def invalidate_symbol_cache(self, symbol: str) -> None:
        """シンボル情報キャッシュを破棄する"""
        self._symbol_cache.pop(symbol, None)

    def get_symbol_info(self, symbol: str, refresh: bool = False) -> dict | None:
        """取引ペアの情報を取得（キャッシュ付き、TTL期限切れで更新）"""
        now = time.time()
        if not refresh and symbol in self._symbol_cache:
            cached_info, cached_time = self._symbol_cache[symbol]
            if now - cached_time < SYMBOL_CACHE_TTL:
                return cached_info
            logger.debug(f"シンボルキャッシュ期限切れ: {symbol}")

        data = self._make_request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
        symbols = data.get("symbols", [])
        if not symbols:
            return None

        info = self._parse_symbol_info(symbols[0])
        self._symbol_cache[symbol] = (info, now)
        return info

    @staticmethod
    def _parse_symbol_info(s: dict) -> dict:
        """exchangeInfo レスポンスの1シンボルをパース"""
        filters = {f["filterType"]: f for f in s["filters"]}
        return {
            "symbol": s["symbol"],
            "status": s["status"],
            "base_asset": s["baseAsset"],
            "quote_asset": s["quoteAsset"],
            "price_precision": s.get("pricePrecision", 8),
            "quantity_precision": s.get("quantityPrecision", 6),
            "min_qty": float(filters.get("LOT_SIZE", {}).get("minQty", 0)),
            "max_qty": float(filters.get("LOT_SIZE", {}).get("maxQty", 0)),
            "step_size": float(filters.get("LOT_SIZE", {}).get("stepSize", 0)),
            "min_notional": float(
                (filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}).get("minNotional", 0)
            ),
            "tick_size": float(filters.get("PRICE_FILTER", {}).get("tickSize", 0)),
        }

    def place_order(
        self, symbol: str, side: str, quantity: float, price: float | None = None
    ) -> dict:
        """注文を出す"""
        for attempt in range(2):
            symbol_info = self.get_symbol_info(symbol, refresh=attempt > 0)
            price_precision = 8
            if symbol_info and symbol_info.get("tick_size"):
                price_precision = get_precision(symbol_info["tick_size"])

            quantity_precision = 8
            if symbol_info and symbol_info.get("step_size"):
                quantity_precision = get_precision(symbol_info["step_size"])

            normalized_qty, normalized_price = self._validate_order_request(
                symbol, side, quantity, price, symbol_info
            )

            params = {
                "symbol": symbol,
                "side": side,
                "type": "LIMIT" if normalized_price else "MARKET",
                "quantity": self._format_value(normalized_qty, quantity_precision),
                "timeInForce": "GTC" if normalized_price else None,
            }
            if normalized_price:
                params["price"] = self._format_value(normalized_price, price_precision)
            params = {k: v for k, v in params.items() if v is not None}

            price_str = (
                self._format_value(normalized_price, price_precision)
                if normalized_price
                else "MARKET"
            )
            logger.info(f"注文実行: {side} {normalized_qty} {symbol} @ {price_str} (raw={price})")
            try:
                return self._make_request("POST", "/api/v3/order", params, signed=True)
            except BinanceAPIError as e:
                if attempt == 0 and self._should_refresh_symbol_info(e):
                    logger.warning(
                        "注文が銘柄フィルターと一致しません。exchangeInfo を再取得して再試行します "
                        f"(status={e.status_code}, endpoint={e.endpoint})"
                    )
                    self.invalidate_symbol_cache(symbol)
                    continue
                logger.error(f"注文失敗詳細: {side} {normalized_qty} {symbol} @ {price_str} -> {e}")
                raise

        raise BinanceAPIError(f"注文失敗: {side} {symbol}")

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """注文をキャンセル"""
        params = {"symbol": symbol, "orderId": order_id}
        logger.info(f"注文キャンセル: {symbol} - {order_id}")
        return self._make_request("DELETE", "/api/v3/order", params, signed=True)

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        """オープン中の注文を取得"""
        params = {"symbol": symbol} if symbol else {}
        result = self._make_request("GET", "/api/v3/openOrders", params, signed=True)
        return result if isinstance(result, list) else [result]

    def get_order(self, symbol: str, order_id: int) -> dict:
        """注文の詳細を取得"""
        params = {"symbol": symbol, "orderId": order_id}
        return self._make_request("GET", "/api/v3/order", params, signed=True)

    # ── User Data Stream ─────────────────────────────────────────────

    def create_listen_key(self) -> str:
        """ユーザーデータストリーム用 listenKey を作成"""
        data = self._make_request("POST", "/api/v3/userDataStream")
        listen_key = data["listenKey"]
        logger.info("listenKey 作成完了")
        return listen_key

    def keepalive_listen_key(self, listen_key: str):
        """listenKey の有効期限を延長（30分間有効）"""
        self._make_request("PUT", "/api/v3/userDataStream", {"listenKey": listen_key})
        logger.debug("listenKey 延長完了")

    def close_listen_key(self, listen_key: str):
        """listenKey を閉じる（ストリーム終了時）"""
        self._make_request("DELETE", "/api/v3/userDataStream", {"listenKey": listen_key})
        logger.info("listenKey 閉鎖完了")

    # ── ユーティリティ ────────────────────────────────────────────────

    @staticmethod
    def _format_value(value: float, precision: int) -> str:
        """指定精度でフォーマット（Decimal使用、末尾0削除）"""
        formatted = format_decimal(value, precision)
        if precision > 0:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted

    @staticmethod
    def _should_refresh_symbol_info(error: BinanceAPIError) -> bool:
        """フィルター不整合時にシンボル情報を再取得すべきか判定する"""
        if error.status_code != 400:
            return False
        message = str(error).lower()
        return any(
            token in message
            for token in (
                "filter failure",
                "lot_size",
                "min_notional",
                "price_filter",
                "invalid quantity",
                "invalid price",
            )
        )
