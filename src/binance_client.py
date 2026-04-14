"""
ファイルパス: src/binance_client.py
概要: Binance API クライアント
説明: Binance の現物取引に必要な API 呼び出しをカプセル化
関連ファイル: config/settings.py, src/grid_strategy.py, src/order_manager.py
"""

import time
import hashlib
import hmac
from typing import Optional
from urllib.parse import urlencode

import requests
from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("binance_client")

MAX_RETRIES = 3
RETRY_DELAY = 1
SYMBOL_CACHE_TTL = 300  # シンボル情報のキャッシュ有効期限（秒）


class BinanceAPIError(Exception):
    """Binance API 関連のエラー"""

    pass


class BinanceClient:
    """Binance API クライアント"""

    TESTNET_BASE_URL = "https://testnet.binance.vision"
    MAINNET_BASE_URL = "https://api.binance.com"

    def __init__(self):
        self.base_url = self.TESTNET_BASE_URL if Settings.USE_TESTNET else self.MAINNET_BASE_URL
        self.api_key = Settings.BINANCE_API_KEY
        self.api_secret = Settings.BINANCE_API_SECRET
        self._symbol_cache: dict[str, tuple[dict, float]] = {}

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/json",
            }
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

    def _generate_signature(self, query_string: str) -> str:
        """署名を生成"""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = False,
    ) -> dict:
        """API リクエストを実行（リトライ付き）

        Args:
            method: HTTP メソッド (GET/POST/DELETE)
            endpoint: API エンドポイント
            params: リクエストパラメータ
            signed: 署名付きリクエストかどうか

        Returns:
            API レスポンス

        Raises:
            BinanceAPIError: API エラー時
        """
        url = f"{self.base_url}{endpoint}"
        params = dict(params) if params else {}

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            query_string = urlencode(params)
            params["signature"] = self._generate_signature(query_string)

        # --- 接続エラー（443等）は無制限リトライ ---
        attempt_conn = 0
        while True:
            attempt_conn += 1
            try:
                response = self._send_request(method, url, params)
                if response.status_code == 429:
                    retry_after = int(
                        response.headers.get("Retry-After", RETRY_DELAY * (2**attempt_conn))
                    )
                    logger.warning(
                        f"レートリミット到達、{retry_after}秒後にリトライ ({attempt_conn}回目)"
                    )
                    time.sleep(retry_after)
                    continue
                if response.status_code >= 500:
                    wait_time = RETRY_DELAY * (2 ** min(attempt_conn, 5))
                    logger.warning(
                        f"サーバーエラー ({response.status_code})、{wait_time}秒後にリトライ ({attempt_conn}回目)"
                    )
                    time.sleep(wait_time)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.ConnectionError as e:
                wait_time = min(RETRY_DELAY * (2 ** min(attempt_conn, 5)), 60)
                logger.warning(
                    f"接続エラー（443等）、{wait_time}秒後にリトライ ({attempt_conn}回目): {e}"
                )
                time.sleep(wait_time)
                continue
            except requests.exceptions.HTTPError as e:
                status_code = getattr(e.response, "status_code", 0) if e.response else 0
                if 400 <= status_code < 500:
                    response_text = e.response.text if e.response else ""
                    logger.error(f"クライアントエラー ({status_code}): {response_text}")
                    raise BinanceAPIError(
                        f"クライアントエラー: {status_code} - {response_text}"
                    ) from e
                wait_time = RETRY_DELAY * (2 ** min(attempt_conn, 5))
                logger.warning(f"HTTP エラー、{wait_time}秒後にリトライ ({attempt_conn}回目)")
                time.sleep(wait_time)
                continue
            except requests.exceptions.Timeout as e:
                wait_time = min(RETRY_DELAY * (2 ** min(attempt_conn, 5)), 60)
                logger.warning(f"タイムアウト、{wait_time}秒後にリトライ ({attempt_conn}回目): {e}")
                time.sleep(wait_time)
                continue
            except requests.exceptions.RequestException as e:
                wait_time = min(RETRY_DELAY * (2 ** min(attempt_conn, 5)), 60)
                logger.warning(
                    f"リクエスト失敗、{wait_time}秒後にリトライ ({attempt_conn}回目): {e}"
                )
                time.sleep(wait_time)
                continue

    def _send_request(self, method: str, url: str, params: dict) -> requests.Response:
        """HTTP リクエストを送信"""
        if method == "GET":
            return self.session.get(url, params=params, timeout=10)
        elif method == "POST":
            return self.session.post(url, data=params, timeout=10)
        elif method == "DELETE":
            return self.session.delete(url, params=params, timeout=10)
        else:
            raise ValueError(f"サポートされていない HTTP メソッド: {method}")

    @staticmethod
    def _format_value(value: float, precision: int) -> str:
        """指定精度でフォーマット（不要なゼロを除去）"""
        return f"{value:.{precision}f}".rstrip("0").rstrip(".")

    def get_account_balance(self) -> dict:
        """アカウント残高を取得

        Returns:
            残高情報 {"USDT": {"free": 100.0, "locked": 0.0}, ...}
        """
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

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
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

        s = symbols[0]
        filters = {f["filterType"]: f for f in s["filters"]}
        info = {
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
        self._symbol_cache[symbol] = (info, now)
        return info

    def place_order(
        self, symbol: str, side: str, quantity: float, price: Optional[float] = None
    ) -> dict:
        """注文を出す

        Args:
            symbol: 取引ペア
            side: BUY または SELL
            quantity: 数量
            price: 価格（指値の場合必須、成行の場合は None）

        Returns:
            注文情報
        """
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

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """オープン中の注文を取得"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._make_request("GET", "/api/v3/openOrders", params, signed=True)

    def get_order(self, symbol: str, order_id: int) -> dict:
        """注文の詳細を取得"""
        params = {"symbol": symbol, "orderId": order_id}
        return self._make_request("GET", "/api/v3/order", params, signed=True)
