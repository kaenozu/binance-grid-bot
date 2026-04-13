"""
ファイルパス: src/order_manager.py
概要: 注文管理
説明: グリッド注文の配置・監視・キャンセル・再配置を管理
関連ファイル: src/binance_client.py, src/grid_strategy.py, src/portfolio.py
"""

from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from utils.logger import setup_logger

logger = setup_logger("order_manager")


class OrderManager:
    """注文管理クラス"""

    def __init__(self, client: BinanceClient, strategy: GridStrategy):
        self.client = client
        self.strategy = strategy
        self._active_orders: dict[int, dict] = {}

        logger.info("注文マネージャー初期化")

    @property
    def active_orders(self) -> dict[int, dict]:
        """アクティブ注文の読み取り専用ビュー"""
        return dict(self._active_orders)

    def register_order(
        self,
        order_id: int,
        grid_level: int,
        side: str,
        price: float,
        quantity: float,
        status: str,
    ):
        """注文を内部管理に登録"""
        self._active_orders[order_id] = {
            "grid_level": grid_level,
            "side": side,
            "price": price,
            "quantity": quantity,
            "status": status,
        }

    def place_grid_orders(self) -> dict:
        """グリッド注文を一括配置

        Returns:
            配置結果 {"placed": 数, "errors": エラーリスト}
        """
        symbol_info = self.client.get_symbol_info(self.strategy.symbol)
        if not symbol_info:
            logger.error(f"シンボル情報取得失敗: {self.strategy.symbol}")
            return {"placed": 0, "errors": ["シンボル情報取得失敗"]}

        placed_count = 0
        errors = []

        for grid in self.strategy.get_active_buy_grids():
            if grid.position_filled:
                continue

            try:
                quantity = self.strategy.get_order_quantity(
                    grid.buy_price, symbol_info["min_qty"], symbol_info["step_size"]
                )
                if quantity <= 0:
                    logger.warning(f"グリッド {grid.level}: 無効な数量 {quantity}")
                    continue

                adjusted_price = (
                    round(grid.buy_price / symbol_info["tick_size"])
                    * symbol_info["tick_size"]
                )

                order = self.client.place_order(
                    symbol=self.strategy.symbol,
                    side="BUY",
                    quantity=quantity,
                    price=adjusted_price,
                )

                self.register_order(
                    order_id=order["orderId"],
                    grid_level=grid.level,
                    side="BUY",
                    price=float(order["price"]),
                    quantity=float(order["origQty"]),
                    status=order["status"],
                )

                if order["status"] == "FILLED":
                    self.strategy.mark_position_filled(grid.level, order["orderId"])
                    logger.info(f"グリッド {grid.level}: 即約定 @ {adjusted_price}")
                else:
                    self.strategy.grids[grid.level].buy_order_id = order["orderId"]
                    logger.info(
                        f"グリッド {grid.level}: 買い注文配置 @ {adjusted_price}, qty={quantity}"
                    )

                placed_count += 1

            except Exception as e:
                error_msg = f"グリッド {grid.level} 買い注文失敗: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        for grid in self.strategy.get_active_sell_grids():
            try:
                buy_order_id = grid.buy_order_id
                if buy_order_id and buy_order_id in self._active_orders:
                    quantity = self._active_orders[buy_order_id]["quantity"]
                else:
                    quantity = self.strategy.get_order_quantity(
                        grid.buy_price, symbol_info["min_qty"], symbol_info["step_size"]
                    )

                if quantity <= 0:
                    continue

                adjusted_price = (
                    round(grid.sell_price / symbol_info["tick_size"])
                    * symbol_info["tick_size"]
                )

                order = self.client.place_order(
                    symbol=self.strategy.symbol,
                    side="SELL",
                    quantity=quantity,
                    price=adjusted_price,
                )

                self.register_order(
                    order_id=order["orderId"],
                    grid_level=grid.level,
                    side="SELL",
                    price=float(order["price"]),
                    quantity=float(order["origQty"]),
                    status=order["status"],
                )

                if order["status"] == "FILLED":
                    self.strategy.mark_position_closed(grid.level, order["orderId"])
                    logger.info(f"グリッド {grid.level}: 売り即約定 @ {adjusted_price}")
                else:
                    self.strategy.grids[grid.level].sell_order_id = order["orderId"]
                    logger.info(
                        f"グリッド {grid.level}: 売り注文配置 @ {adjusted_price}, qty={quantity}"
                    )

                placed_count += 1

            except Exception as e:
                error_msg = f"グリッド {grid.level} 売り注文失敗: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"注文配置完了: {placed_count} 件, エラー: {len(errors)} 件")
        return {"placed": placed_count, "errors": errors}

    def check_order_fills(self) -> list[dict]:
        """約定済み注文をチェックし、新規約定があれば処理してクリーンアップ

        Returns:
            新規約定リスト
        """
        new_fills = []

        for order_id, order_info in list(self._active_orders.items()):
            if order_info["status"] == "FILLED":
                continue

            try:
                order = self.client.get_order(self.strategy.symbol, order_id)

                if order["status"] == "FILLED":
                    order_info["status"] = "FILLED"
                    grid_level = order_info["grid_level"]
                    executed_qty = float(order["executedQty"])

                    if order_info["side"] == "BUY":
                        self.strategy.mark_position_filled(grid_level, order_id)
                        logger.info(
                            f"グリッド {grid_level}: 買い約定完了 @ {float(order['price'])}"
                        )
                    elif order_info["side"] == "SELL":
                        self.strategy.mark_position_closed(grid_level, order_id)
                        logger.info(
                            f"グリッド {grid_level}: 売り約定完了 @ {float(order['price'])}"
                        )

                    new_fills.append(
                        {
                            "grid": grid_level,
                            "side": order_info["side"],
                            "price": float(order["price"]),
                            "quantity": executed_qty,
                            "order_id": order_id,
                        }
                    )

            except Exception as e:
                logger.error(f"注文状態確認失敗 order_id={order_id}: {e}")

        self.cleanup_filled_orders()
        return new_fills

    def cancel_all_orders(self) -> int:
        """すべてのアクティブ注文をキャンセル

        Returns:
            キャンセル件数
        """
        open_orders = self.client.get_open_orders(self.strategy.symbol)
        canceled_count = 0

        for order in open_orders:
            try:
                self.client.cancel_order(self.strategy.symbol, order["orderId"])
                self._active_orders.pop(order["orderId"], None)
                canceled_count += 1
                logger.info(f"注文キャンセル: {order['orderId']}")
            except Exception as e:
                logger.error(f"注文キャンセル失敗: {e}")

        logger.info(f"注文キャンセル完了: {canceled_count} 件")
        return canceled_count

    def cleanup_filled_orders(self):
        """約定済み注文を内部管理から除去"""
        filled_ids = [
            oid
            for oid, info in self._active_orders.items()
            if info["status"] == "FILLED"
        ]
        for oid in filled_ids:
            del self._active_orders[oid]

        if filled_ids:
            logger.info(f"約定済み注文クリーンアップ: {len(filled_ids)} 件")

    def get_active_order_count(self) -> int:
        """未約定のアクティブ注文数"""
        return sum(1 for o in self._active_orders.values() if o["status"] != "FILLED")
