"""ペーパートレード用クライアント

ファイルの役割: テスト用の疑似取引を実現（Binance API不要）
なぜ存在するか: 風險なく取引ロジックをテストするため
関連ファイル: binance_client.py（本番クライアント）, bot.py（メインループ）
"""

import time as _time

import requests as requests_lib

from src.binance_client import BinanceAPIError
from utils.logger import setup_logger

logger = setup_logger("paper_client")


class PaperClient:
    """ペーパートレード用クライアント（注文を出さず内部記録のみ）"""

    def __init__(self, base_url: str = "", api_key: str = "", api_secret: str = ""):
        self.base_url = base_url or "https://testnet.binance.vision"
        self._order_counter = 100000
        self._orders: list[dict] = []
        self._balances: dict = {
            "USDT": {"free": 10000.0, "locked": 0.0},
            "BTC": {"free": 0.0, "locked": 0.0},
        }
        self._price_cache: dict[str, tuple[float, float]] = {}  # {symbol: (price, timestamp)}
        self._price_cache_ttl = 5.0  # seconds

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ── 公開 API ─────────────────────────────────────────────────────

    def get_account_balance(self) -> dict:
        return dict(self._balances)

    def get_symbol_price(self, symbol: str) -> float:
        now = _time.time()
        if symbol in self._price_cache:
            cached_price, cached_time = self._price_cache[symbol]
            if now - cached_time < self._price_cache_ttl:
                return cached_price
        response = requests_lib.get(
            "https://testnet.binance.vision/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=10,
        )
        response.raise_for_status()
        price = float(response.json()["price"])
        self._price_cache[symbol] = (price, now)
        return price

    def get_symbol_info(self, symbol: str) -> dict | None:
        return {
            "symbol": symbol,
            "status": "TRADING",
            "base_asset": symbol.replace("USDT", ""),
            "quote_asset": "USDT",
            "price_precision": 2,
            "quantity_precision": 6,
            "min_qty": 0.00001,
            "max_qty": 9000.0,
            "step_size": 0.00001,
            "min_notional": 10.0,
            "tick_size": 0.01,
        }

    def place_order(
        self, symbol: str, side: str, quantity: float, price: float | None = None
    ) -> dict:
        self._order_counter += 1
        base = symbol.replace("USDT", "") if "USDT" in symbol else "BTC"
        quote = "USDT"

        if price is None:
            # 成行注文: 即時約定
            fill_price = self.get_symbol_price(symbol)
            order = self._build_order(
                self._order_counter, symbol, side, fill_price, quantity, "FILLED"
            )
            self._settle_order(order, base, quote, fill_price)
        else:
            # 指値注文: 残高チェック
            self._check_balance(side, base, quote, price, quantity)
            order = self._build_order(self._order_counter, symbol, side, price, quantity, "NEW")

        self._orders.append(order)
        return order

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        for o in self._orders:
            if o["orderId"] == order_id:
                o["status"] = "CANCELED"
                return {"orderId": order_id, "status": "CANCELED"}
        return {"orderId": order_id, "status": "CANCELED"}

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        orders = [o for o in self._orders if o["status"] == "NEW"]
        if symbol is not None:
            orders = [o for o in orders if o["symbol"] == symbol]
        return orders

    def get_order(self, symbol: str, order_id: int) -> dict:
        """注文情報を取得。NEW（指値）注文は現在価格と比較して自動フィルする。

        WARNING: フィル時に残高を更新する副作用がある。ペーパートレード専用。
        """
        for o in self._orders:
            if o["orderId"] != order_id:
                continue
            self._try_auto_fill(o, symbol)
            return o
        raise BinanceAPIError(f"注文が見つかりません: {order_id}")

    # ── プライベートヘルパー ─────────────────────────────────────────

    def _build_order(
        self,
        order_id: int,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        status: str,
    ) -> dict:
        qty_str = f"{quantity:.8f}"
        return {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "type": "LIMIT" if status == "NEW" else "MARKET",
            "price": f"{price:.8f}",
            "origQty": qty_str,
            "executedQty": qty_str if status == "FILLED" else "0",
            "status": status,
            "avgPrice": f"{price:.8f}" if status == "FILLED" else "0",
        }

    def _check_balance(self, side: str, base: str, quote: str, price: float, quantity: float):
        """残高不足なら BinanceAPIError を送出"""
        if side == "BUY":
            cost = price * quantity
            avail = self._balances.get(quote, {}).get("free", 0)
            if quote in self._balances and avail < cost:
                raise BinanceAPIError(f"残高不足: {quote} needed={cost:.2f}, available={avail:.2f}")
        elif side == "SELL":
            avail = self._balances.get(base, {}).get("free", 0)
            if base in self._balances and avail < quantity:
                raise BinanceAPIError(
                    f"残高不足: {base} needed={quantity:.8f}, available={avail:.8f}"
                )

    def _settle_order(self, order: dict, base: str, quote: str, price: float):
        """注文を約定状態にし、残高を更新"""
        qty = float(order["origQty"])
        if order["side"] == "BUY":
            cost = price * qty
            if quote in self._balances and self._balances[quote]["free"] >= cost:
                self._balances[quote]["free"] -= cost
            if base in self._balances:
                self._balances[base]["free"] += qty
        elif order["side"] == "SELL":
            if base in self._balances and self._balances[base]["free"] >= qty:
                self._balances[base]["free"] -= qty
            proceeds = price * qty
            if quote in self._balances:
                self._balances[quote]["free"] += proceeds
        order["executedQty"] = f"{qty:.8f}"

    def _try_auto_fill(self, order: dict, symbol: str):
        """NEW 指値注文を内部価格で評価し、条件を満たせば約定させる"""
        if order["status"] != "NEW" or order["price"] == "0":
            return
        try:
            current = self._get_cached_price(symbol)
            limit_price = float(order["price"])
            is_buy = current <= limit_price
            is_sell = current >= limit_price
            if not ((order["side"] == "BUY" and is_buy) or (order["side"] == "SELL" and is_sell)):
                return
            base = symbol.replace("USDT", "") if "USDT" in symbol else "BTC"
            quote = "USDT"
            order["status"] = "FILLED"
            order["avgPrice"] = order["price"]
            order["executedQty"] = order["origQty"]
            self._settle_order(order, base, quote, limit_price)
        except Exception as e:
            logger.debug(f"自動フィル失敗: {e}")

    def _get_cached_price(self, symbol: str) -> float:
        """キャッシュから価格を返す（なければAPI取得）"""
        if symbol in self._price_cache:
            cached_price, _ = self._price_cache[symbol]
            return cached_price
        return self.get_symbol_price(symbol)
