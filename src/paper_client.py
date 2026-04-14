"""
ファイルパス: src/paper_client.py
概要: ペーパートレード用APIクライアント
説明: 実際の注文を出さずにシミュレーションのみ行う
関連ファイル: src/binance_client.py, src/bot.py
"""

from typing import Optional

import requests as requests_lib

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

        if price is None:
            market_price = self.get_symbol_price(symbol)
            fill_price = market_price
            status = "FILLED"
        else:
            fill_price = price
            status = "NEW"

        order = {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "type": "LIMIT" if price else "MARKET",
            "price": f"{fill_price:.8f}",
            "origQty": f"{quantity:.8f}",
            "executedQty": f"{quantity:.8f}" if status == "FILLED" else "0",
            "status": status,
            "avgPrice": f"{fill_price:.8f}" if status == "FILLED" else "0",
        }

        if status == "FILLED":
            base = symbol.replace("USDT", "") if "USDT" in symbol else "BTC"
            quote = "USDT"
            if side == "BUY":
                cost = fill_price * quantity
                if quote in self._balances and self._balances[quote]["free"] >= cost:
                    self._balances[quote]["free"] -= cost
                    if base in self._balances:
                        self._balances[base]["free"] += quantity
                order["executedQty"] = f"{quantity:.8f}"
            elif side == "SELL":
                if base in self._balances and self._balances[base]["free"] >= quantity:
                    self._balances[base]["free"] -= quantity
                    proceeds = fill_price * quantity
                    if quote in self._balances:
                        self._balances[quote]["free"] += proceeds
                order["executedQty"] = f"{quantity:.8f}"

        self._orders.append(order)
        return order

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        for o in self._orders:
            if o["orderId"] == order_id:
                o["status"] = "CANCELED"
                return {"orderId": order_id, "status": "CANCELED"}
        return {"orderId": order_id, "status": "CANCELED"}

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        orders = [o for o in self._orders if o["status"] == "NEW"]
        if symbol is not None:
            orders = [o for o in orders if o["symbol"] == symbol]
        return orders

    def get_order(self, symbol: str, order_id: int) -> dict:
        for o in self._orders:
            if o["orderId"] == order_id:
                if o["status"] == "NEW" and o["price"] != "0":
                    try:
                        current = self.get_symbol_price(symbol)
                        limit_price = float(o["price"])
                        filled = (o["side"] == "BUY" and current <= limit_price) or (
                            o["side"] == "SELL" and current >= limit_price
                        )
                        if filled:
                            qty = float(o["origQty"])
                            o["status"] = "FILLED"
                            o["avgPrice"] = o["price"]
                            o["executedQty"] = o["origQty"]
                            base = symbol.replace("USDT", "") if "USDT" in symbol else "BTC"
                            quote = "USDT"
                            if o["side"] == "BUY":
                                cost = limit_price * qty
                                if quote in self._balances:
                                    self._balances[quote]["free"] -= cost
                                if base in self._balances:
                                    self._balances[base]["free"] += qty
                            elif o["side"] == "SELL":
                                if base in self._balances:
                                    self._balances[base]["free"] -= qty
                                proceeds = limit_price * qty
                                if quote in self._balances:
                                    self._balances[quote]["free"] += proceeds
                    except Exception:
                        pass
                return o
        raise BinanceAPIError(f"注文が見つかりません: {order_id}")
