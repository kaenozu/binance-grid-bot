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

# リトライ設定
MAX_RETRIES = 3
RETRY_DELAY = 1  # 秒


class BinanceAPIError(Exception):
    """Binance API 関連のエラー"""
    pass


class BinanceClient:
    """Binance API クライアント"""
    
    # Testnet と本番のベース URL
    TESTNET_BASE_URL = "https://testnet.binance.vision"
    MAINNET_BASE_URL = "https://api.binance.com"
    
    def __init__(self):
        self.base_url = self.TESTNET_BASE_URL if Settings.USE_TESTNET else self.MAINNET_BASE_URL
        self.api_key = Settings.BINANCE_API_KEY
        self.api_secret = Settings.BINANCE_API_SECRET
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/json"
        })
        
        logger.info(f"Binance クライアント初期化完了 (Testnet: {Settings.USE_TESTNET})")
    
    def _generate_signature(self, query_string: str) -> str:
        """署名を生成"""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, method: str, endpoint: str, params: Optional[dict] = None, signed: bool = False) -> dict:
        """API リクエストを実行
        
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
        
        if params is None:
            params = {}
        
        # 署名付きリクエストの場合
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            query_string = urlencode(params)
            params["signature"] = self._generate_signature(query_string)
        
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                if method == "GET":
                    response = self.session.get(url, params=params, timeout=10)
                elif method == "POST":
                    response = self.session.post(url, data=params, timeout=10)
                elif method == "DELETE":
                    response = self.session.delete(url, params=params, timeout=10)
                else:
                    raise ValueError(f"サポートされていない HTTP メソッド: {method}")
                
                # レートリミットチェック
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_DELAY * (2 ** attempt)))
                    logger.warning(f"レートリミット到達、{retry_after}秒後にリトライ ({attempt + 1}/{MAX_RETRIES})")
                    time.sleep(retry_after)
                    last_error = BinanceAPIError(f"レートリミット到達")
                    continue
                
                # 5xx エラーはリトライ可能
                if response.status_code >= 500:
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"サーバーエラー ({response.status_code})、{wait_time}秒後にリトライ ({attempt + 1}/{MAX_RETRIES})")
                    time.sleep(wait_time)
                    last_error = BinanceAPIError(f"サーバーエラー: {response.status_code}")
                    continue
                
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.Timeout as e:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"リクエストタイムアウト、{wait_time}秒後にリトライ ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait_time)
                last_error = BinanceAPIError(f"タイムアウト: {e}")
                continue
                
            except requests.exceptions.ConnectionError as e:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"接続エラー、{wait_time}秒後にリトライ ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait_time)
                last_error = BinanceAPIError(f"接続エラー: {e}")
                continue
                
            except requests.exceptions.HTTPError as e:
                # 4xx エラーはリトライ不可（クライアントエラー）
                if 400 <= response.status_code < 500:
                    logger.error(f"クライアントエラー ({response.status_code}): {response.text}")
                    raise BinanceAPIError(f"クライアントエラー: {response.status_code} - {response.text}") from e
                raise BinanceAPIError(f"HTTP エラー: {e}") from e
                
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"API リクエスト失敗、{wait_time}秒後にリトライ ({attempt + 1}/{MAX_RETRIES}): {e}")
                    time.sleep(wait_time)
                    last_error = BinanceAPIError(f"リクエスト失敗: {e}")
                    continue
                raise BinanceAPIError(f"API リクエスト失敗: {e}") from e
        
        # リトライ上限到達
        logger.error(f"リトライ上限到達 ({MAX_RETRIES} 回)")
        raise last_error or BinanceAPIError("リトライ上限到達")
    
    def get_account_balance(self) -> dict:
        """アカウント残高を取得
        
        Returns:
            残高情報 {"USDT": {"free": "100.0", "locked": "0.0"}, ...}
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
        """現在の価格を取得
        
        Args:
            symbol: 取引ペア (例: BTCUSDT)
            
        Returns:
            現在価格
        """
        data = self._make_request("GET", "/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])
    
    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """取引ペアの情報を取得
        
        Args:
            symbol: 取引ペア
            
        Returns:
            シンボル情報（精度、最小注文数量など）
        """
        data = self._make_request("GET", "/api/v3/exchangeInfo")
        
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                # フィルター情報を抽出
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
        
        return None
    
    def place_order(self, symbol: str, side: str, quantity: float, price: Optional[float] = None) -> dict:
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
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            "timeInForce": "GTC" if price else None
        }
        
        if price:
            params["price"] = f"{price:.8f}".rstrip("0").rstrip(".")
        
        # None のパラメータを削除
        params = {k: v for k, v in params.items() if v is not None}
        
        logger.info(f"注文実行: {side} {quantity} {symbol} @ {price or 'MARKET'}")
        return self._make_request("POST", "/api/v3/order", params, signed=True)
    
    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """注文をキャンセル
        
        Args:
            symbol: 取引ペア
            order_id: 注文 ID
            
        Returns:
            キャンセル結果
        """
        params = {
            "symbol": symbol,
            "orderId": order_id
        }
        
        logger.info(f"注文キャンセル: {symbol} - {order_id}")
        return self._make_request("DELETE", "/api/v3/order", params, signed=True)
    
    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """オープン中の注文を取得
        
        Args:
            symbol: 取引ペア（None ですべて取得）
            
        Returns:
            オープン注文のリスト
        """
        params = {}
        if symbol:
            params["symbol"] = symbol
        
        return self._make_request("GET", "/api/v3/openOrders", params, signed=True)
    
    def get_order(self, symbol: str, order_id: int) -> dict:
        """注文の詳細を取得
        
        Args:
            symbol: 取引ペア
            order_id: 注文 ID
            
        Returns:
            注文詳細
        """
        params = {
            "symbol": symbol,
            "orderId": order_id
        }
        
        return self._make_request("GET", "/api/v3/order", params, signed=True)
