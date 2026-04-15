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

logger = setup_logger("binance_client")

RETRY_DELAY = 1
MAX_CONNECTION_RETRIES = 10
SYMBOL_CACHE_TTL = 300  # シンボル情報のキャッシュ有効期限（秒）


class BinanceAPIError(Exception):
    """Binance API 関連のエラー"""


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
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        params["signature"] = self._generate_signature(query_string)

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

            # 4xx ── リトライしない（クライアントエラー）
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                body = e.response.text if e.response else ""
                status = getattr(e.response, "status_code", 0)
                logger.error(f"クライアントエラー ({status}): {body}")
                raise BinanceAPIError(f"クライアントエラー: {status} - {body}") from e

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

    def get_symbol_info(self, symbol: str) -> dict | None:
        """取引ペアの情報を取得（キャッシュ付き、TTL期限切れで更新）"""
        now = time.time()
        if symbol in self._symbol_cache:
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
            "min_notional": float(filters.get("MIN_NOTIONAL", {}).get("minNotional", 0)),
            "tick_size": float(filters.get("PRICE_FILTER", {}).get("tickSize", 0)),
        }

    def place_order(
        self, symbol: str, side: str, quantity: float, price: float | None = None
    ) -> dict:
        """注文を出す"""
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT" if price else "MARKET",
            "quantity": self._format_value(quantity, 8),
            "timeInForce": "GTC" if price else None,
        }
        if price:
            params["price"] = self._format_value(price, 8)
        params = {k: v for k, v in params.items() if v is not None}

        logger.info(f"注文実行: {side} {quantity} {symbol} @ {price or 'MARKET'}")
        return self._make_request("POST", "/api/v3/order", params, signed=True)

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

    # ── ユーティリティ ────────────────────────────────────────────────

    @staticmethod
    def _format_value(value: float, precision: int) -> str:
        """指定精度でフォーマット（不要なゼロを除去）"""
        return f"{value:.{precision}f}".rstrip("0").rstrip(".")
