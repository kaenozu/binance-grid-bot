"""
ファイルパス: src/paper_client.py
概要: ペーパートレード用APIクライアント
説明: 実際の注文を出さずにシミュレーションのみ行う
関連ファイル: src/binance_client.py, src/bot.py
"""

import requests as requests_lib
from typing import Optional

from src.binance_client import BinanceAPIError


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

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def get_account_balance(self) -> dict:
        return dict(self._balances)

    def get_symbol_price(self, symbol: str) -> float:
        response = requests_lib.get(
            "https://testnet.binance.vision/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=10,
        )
        response.raise_for_status()
        return float(response.json()["price"])

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
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
        self, symbol: str, side: str, quantity: float, price: Optional[float] = None
    ) -> dict:
        self._order_counter += 1
        order_id = self._order_counter
        order = {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "type": "LIMIT" if price else "MARKET",
            "price": f"{price:.8f}" if price else "0",
            "origQty": f"{quantity:.8f}",
            "executedQty": f"{quantity:.8f}",
            "status": "NEW",
            "avgPrice": f"{price:.8f}" if price else "0",
        }

        if price is None:
            order["status"] = "FILLED"
            order["avgPrice"] = order["price"]

        self._orders.append(order)

        if side == "BUY" and price is not None:
            quote = symbol.replace("USDT", "") if "USDT" in symbol else "BTC"
            if quote in self._balances:
                self._balances[quote]["free"] += quantity
        elif side == "BUY" and price is None:
            quote = symbol.replace("USDT", "") if "USDT" in symbol else "BTC"
            if quote in self._balances:
                self._balances[quote]["free"] += quantity

        return order

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        return {"orderId": order_id, "status": "CANCELED"}

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        return [o for o in self._orders if o["status"] == "NEW"]

    def get_order(self, symbol: str, order_id: int) -> dict:
        for o in self._orders:
            if o["orderId"] == order_id:
                return o
        raise BinanceAPIError(f"注文が見つかりません: {order_id}")
