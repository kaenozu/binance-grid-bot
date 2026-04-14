"""
ファイルパス: src/order_manager.py
概要: 注文管理
説明: グリッド注文の配置・監視・キャンセル・再配置を管理
関連ファイル: src/binance_client.py, src/grid_strategy.py, src/portfolio.py
"""

import math
from dataclasses import dataclass, field

from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from utils.logger import setup_logger

logger = setup_logger("order_manager")


@dataclass
class OrderRecord:
    """注文記録"""

    order_id: int
    grid_level: int
    side: str
    price: float
    quantity: float
    status: str


@dataclass
class FillEvent:
    """約定イベント"""

    grid: int
    side: str
    price: float
    quantity: float
    order_id: int


@dataclass
class OrderPlacementResult:
    """注文配置結果"""

    placed: int
    errors: list[str] = field(default_factory=list)


class OrderManager:
    """注文管理クラス"""

    def __init__(self, client: BinanceClient, strategy: GridStrategy):
        self.client = client
        self.strategy = strategy
        self._active_orders: dict[int, OrderRecord] = {}

        logger.info("注文マネージャー初期化")

    @property
    def active_orders(self) -> dict[int, OrderRecord]:
        """アクティブ注文の読み取り専用ビュー"""
        return dict(self._active_orders)

    def get_active_order_ids(self) -> set[int]:
        return set(self._active_orders.keys())

    def remove_order(self, order_id: int) -> None:
        self._active_orders.pop(order_id, None)

    def register_order(
        self,
        order_id: int,
        grid_level: int,
        side: str,
        price: float,
        quantity: float,
        status: str,
    ) -> OrderRecord:
        """注文を内部管理に登録"""
        order = OrderRecord(
            order_id=order_id,
            grid_level=grid_level,
            side=side,
            price=price,
            quantity=quantity,
            status=status,
        )
        self._active_orders[order_id] = order
        return order

    def _place_order(
        self, grid_level: int, side: str, price: float, quantity: float | None = None
    ) -> dict | None:
        """共通注文配置ロジック"""
        symbol_info = self.client.get_symbol_info(self.strategy.symbol)
        if not symbol_info:
            return None

        if quantity is None:
            grid = self.strategy.grids[grid_level]
            quantity = self.strategy.get_order_quantity(
                grid.buy_price, symbol_info["min_qty"], symbol_info["step_size"]
            )

        if quantity <= 0:
            return None

        adjusted_price = self._adjust_price(price, symbol_info["tick_size"], side=side)
        order = self.client.place_order(
            symbol=self.strategy.symbol,
            side=side,
            quantity=quantity,
            price=adjusted_price,
        )
        self._register_and_handle(order, grid_level, side, adjusted_price, quantity)
        return order

    def place_grid_orders(self) -> OrderPlacementResult:
        """グリッド注文を一括配置

        Returns:
            配置結果
        """
        placed_count = 0
        errors: list[str] = []

        symbol_info = self.client.get_symbol_info(self.strategy.symbol)
        if not symbol_info:
            logger.error(f"シンボル情報取得失敗: {self.strategy.symbol}")
            return OrderPlacementResult(placed=0, errors=["シンボル情報取得失敗"])

        for grid in self.strategy.get_active_buy_grids():
            if grid.position_filled:
                continue

            try:
                result = self._place_order(grid.level, "BUY", grid.buy_price)
                if result is not None:
                    placed_count += 1
                else:
                    logger.warning(
                        f"グリッド {grid.level}: 買い注文スキップ"
                        "（数量無効またはシンボル情報取得失敗）"
                    )

            except Exception as e:
                error_msg = f"グリッド {grid.level} 買い注文失敗: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        for grid in self.strategy.get_active_sell_grids():
            try:
                buy_order_id = grid.buy_order_id
                if buy_order_id and buy_order_id in self._active_orders:
                    quantity = self._active_orders[buy_order_id].quantity
                else:
                    quantity = self.strategy.get_order_quantity(
                        grid.buy_price, symbol_info["min_qty"], symbol_info["step_size"]
                    )

                if grid.sell_price is not None:
                    result = self._place_order(grid.level, "SELL", grid.sell_price, quantity)
                if result is not None:
                    placed_count += 1

            except Exception as e:
                error_msg = f"グリッド {grid.level} 売り注文失敗: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"注文配置完了: {placed_count} 件, エラー: {len(errors)} 件")
        return OrderPlacementResult(placed=placed_count, errors=errors)

    def check_order_fills(self) -> list[FillEvent]:
        """約定済み注文をチェックし、新規約定があれば処理してクリーンアップ"""
        new_fills: list[FillEvent] = []
        filled_ids: set[int] = set()

        stale_filled = [oid for oid, info in self._active_orders.items() if info.status == "FILLED"]
        for oid in stale_filled:
            info = self._active_orders.pop(oid, None)
            if info is not None:
                new_fills.append(
                    FillEvent(
                        grid=info.grid_level,
                        side=info.side,
                        price=info.price,
                        quantity=info.quantity,
                        order_id=oid,
                    )
                )
        if stale_filled:
            logger.info(f"残留約定済み注文クリーンアップ: {len(stale_filled)} 件")

        for order_id, order_info in list(self._active_orders.items()):
            try:
                order = self.client.get_order(self.strategy.symbol, order_id)
                if order["status"] != "FILLED":
                    continue
                order_info.status = "FILLED"
                executed_qty = float(order["executedQty"])
                executed_price = float(order.get("avgPrice") or order["price"])

                if order_info.side == "BUY":
                    self.strategy.mark_position_filled(
                        grid_level := order_info.grid_level, order_id
                    )
                    logger.info(f"グリッド {grid_level}: 買い約定完了 @ {executed_price}")
                elif order_info.side == "SELL":
                    self.strategy.mark_position_closed(
                        grid_level := order_info.grid_level, order_id
                    )
                    logger.info(f"グリッド {grid_level}: 売り約定完了 @ {executed_price}")

                grid_level = order_info.grid_level
                new_fills.append(
                    FillEvent(
                        grid=grid_level,
                        side=order_info.side,
                        price=executed_price,
                        quantity=executed_qty,
                        order_id=order_id,
                    )
                )
                filled_ids.add(order_id)

            except Exception as e:
                logger.error(f"注文状態確認失敗 order_id={order_id}: {e}")

        for oid in filled_ids:
            self._active_orders.pop(oid, None)

        if filled_ids:
            logger.info(f"約定済み注文クリーンアップ: {len(filled_ids)} 件")

        return new_fills

    def cancel_all_orders(self) -> int:
        """すべてのアクティブ注文をキャンセル"""
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

    def place_buy_order_for_grid(self, grid_level: int) -> bool:
        """特定グリッドレベルの買い注文を配置（決済後の再注文）"""
        try:
            grid = self.strategy.grids[grid_level]
            result = self._place_order(grid_level, "BUY", grid.buy_price)
            if result is not None:
                grid.position_filled = False
            return result is not None

        except Exception as e:
            logger.error(f"グリッド {grid_level} 再注文失敗: {e}")
            return False

    def place_sell_order_for_grid(self, grid_level: int, quantity: float) -> bool:
        """特定グリッドレベルの売り注文を配置（買い約定後）"""
        try:
            grid = self.strategy.grids[grid_level]
            if not grid.sell_price:
                return False
            result = self._place_order(grid_level, "SELL", grid.sell_price, quantity)
            return result is not None

        except Exception as e:
            logger.error(f"グリッド {grid_level} 売り注文失敗: {e}")
            return False

    def get_active_order_count(self) -> int:
        """未約定のアクティブ注文数"""
        return sum(1 for o in self._active_orders.values() if o.status != "FILLED")

    # ---- Private helpers ----

    @staticmethod
    def _adjust_price(price: float, tick_size: float, side: str = "BUY") -> float:
        """価格をtick_sizeの倍数に調整（BUY: 切り下げ, SELL: 切り上げ）"""
        if side == "BUY":
            return math.floor(price / tick_size) * tick_size
        return math.ceil(price / tick_size) * tick_size

    def _register_and_handle(
        self, order: dict, grid_level: int, side: str, price: float, quantity: float
    ) -> None:
        """注文を登録し、約定済み処理を実行"""
        avg_price = float(order.get("avgPrice") or order["price"])
        executed_qty = float(order.get("executedQty") or order["origQty"])

        self.register_order(
            order_id=order["orderId"],
            grid_level=grid_level,
            side=side,
            price=avg_price,
            quantity=executed_qty,
            status=order["status"],
        )

        if order["status"] == "FILLED":
            if side == "BUY":
                self.strategy.mark_position_filled(grid_level, order["orderId"])
                self.strategy.grids[grid_level].filled_quantity = executed_qty
                logger.info(f"グリッド {grid_level}: 即約定 @ {avg_price}")
            else:
                self.strategy.mark_position_closed(grid_level, order["orderId"])
                logger.info(f"グリッド {grid_level}: 売り即約定 @ {avg_price}")
        else:
            if side == "BUY":
                self.strategy.grids[grid_level].buy_order_id = order["orderId"]
                logger.info(f"グリッド {grid_level}: 買い注文配置 @ {price}, qty={quantity}")
            else:
                self.strategy.grids[grid_level].sell_order_id = order["orderId"]
                logger.info(f"グリッド {grid_level}: 売り注文配置 @ {price}, qty={quantity}")
