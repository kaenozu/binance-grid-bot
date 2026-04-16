"""注文管理

ファイルの役割: グリッド注文的配置・約定チェック・キャンセルを管理
なぜ存在するか: ボットと取引所の間で注文状態を同期するための中心的クラス
関連ファイル: bot.py（メインループ）, binance_client.py（API通信）, grid_strategy.py（戦略）
"""

from dataclasses import dataclass, field

from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from utils.logger import setup_logger
from utils.price_utils import adjust_price

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

    # ── 公開 API ─────────────────────────────────────────────────────

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

    def place_grid_orders(self) -> OrderPlacementResult:
        """グリッド注文を一括配置"""
        placed_count = 0
        errors: list[str] = []

        symbol_info = self.client.get_symbol_info(self.strategy.symbol)
        if not symbol_info:
            logger.error(f"シンボル情報取得失敗: {self.strategy.symbol}")
            return OrderPlacementResult(placed=0, errors=["シンボル情報取得失敗"])

        placed_count, errors = self._place_buy_orders(symbol_info, placed_count, errors)
        placed_count, errors = self._place_sell_orders(symbol_info, placed_count, errors)

        logger.info(f"注文配置完了: {placed_count} 件, エラー: {len(errors)} 件")
        return OrderPlacementResult(placed=placed_count, errors=errors)

    def check_order_fills(self) -> list[FillEvent]:
        """約定済み注文をチェックし、新規約定があれば処理してクリーンアップ"""
        new_fills: list[FillEvent] = []

        # 1) 前回ティックで即約定したがまだ残っている注文
        new_fills.extend(self._drain_stale_filled())

        # 2) 取引所にポーリングして新規約定を検出
        new_fills.extend(self._poll_exchange_fills())

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

    # ── 注文配置プライベート ────────────────────────────────────────

    def _place_order(
        self,
        grid_level: int,
        side: str,
        price: float,
        quantity: float | None = None,
        symbol_info: dict | None = None,
    ) -> dict | None:
        """共通注文配置ロジック"""
        if symbol_info is None:
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

        adjusted_price = adjust_price(price, symbol_info["tick_size"], side=side)
        order = self.client.place_order(
            symbol=self.strategy.symbol,
            side=side,
            quantity=quantity,
            price=adjusted_price,
        )
        self._register_and_handle(order, grid_level, side, adjusted_price, quantity)
        return order

    def _place_buy_orders(
        self, symbol_info: dict, placed_count: int, errors: list[str]
    ) -> tuple[int, list[str]]:
        """買い注文の一括配置"""
        for grid in self.strategy.get_active_buy_grids():
            if grid.position_filled:
                continue
            try:
                result = self._place_order(
                    grid.level, "BUY", grid.buy_price, symbol_info=symbol_info
                )
                if result is not None:
                    placed_count += 1
                else:
                    logger.warning(f"グリッド {grid.level}: 買い注文スキップ（数量無効）")
            except Exception as e:
                errors.append(f"グリッド {grid.level} 買い注文失敗: {e}")
                logger.error(errors[-1])
        return placed_count, errors

    def _place_sell_orders(
        self, symbol_info: dict, placed_count: int, errors: list[str]
    ) -> tuple[int, list[str]]:
        """売り注文の一括配置"""
        for grid in self.strategy.get_active_sell_grids():
            try:
                quantity = self._resolve_sell_quantity(grid, symbol_info)
                if grid.sell_price is not None:
                    result = self._place_order(
                        grid.level,
                        "SELL",
                        grid.sell_price,
                        quantity,
                        symbol_info=symbol_info,
                    )
                    if result is not None:
                        placed_count += 1
            except Exception as e:
                errors.append(f"グリッド {grid.level} 売り注文失敗: {e}")
                logger.error(errors[-1])
        return placed_count, errors

    def _resolve_sell_quantity(self, grid, symbol_info: dict) -> float:
        """売り注文の数量を解決（filled_quantity > buy_order > 計算値）"""
        if grid.filled_quantity is not None:
            return grid.filled_quantity

        buy_order_id = grid.buy_order_id
        if buy_order_id and buy_order_id in self._active_orders:
            return self._active_orders[buy_order_id].quantity

        return self.strategy.get_order_quantity(
            grid.buy_price, symbol_info["min_qty"], symbol_info["step_size"]
        )

    # ── 約定チェックプライベート ────────────────────────────────────

    def _drain_stale_filled(self) -> list[FillEvent]:
        """前回ティックで即約定した残留注文を処理"""
        stale_ids = [oid for oid, info in self._active_orders.items() if info.status == "FILLED"]
        if not stale_ids:
            return []

        fills: list[FillEvent] = []
        for oid in stale_ids:
            info = self._active_orders.pop(oid, None)
            if info is None:
                continue
            self._apply_fill_to_strategy(info.side, info.grid_level, oid)
            fills.append(
                FillEvent(
                    grid=info.grid_level,
                    side=info.side,
                    price=info.price,
                    quantity=info.quantity,
                    order_id=oid,
                )
            )
        logger.info(f"残留約定済み注文クリーンアップ: {len(stale_ids)} 件")
        return fills

    def _poll_exchange_fills(self) -> list[FillEvent]:
        """取引所にポーリングして新規約定を検出"""
        fills: list[FillEvent] = []
        filled_ids: set[int] = set()

        for order_id, order_info in list(self._active_orders.items()):
            try:
                order = self.client.get_order(self.strategy.symbol, order_id)
                if order["status"] != "FILLED":
                    continue
                order_info.status = "FILLED"
                executed_qty = float(order["executedQty"])
                executed_price = float(order.get("avgPrice") or order["price"])

                self._apply_fill_to_strategy(order_info.side, order_info.grid_level, order_id)
                logger.info(
                    f"グリッド {order_info.grid_level}: "
                    f"{order_info.side}約定完了 @ {executed_price}"
                )
                fills.append(
                    FillEvent(
                        grid=order_info.grid_level,
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
        return fills

    def _apply_fill_to_strategy(self, side: str, grid_level: int, order_id: int):
        """戦略のポジション状態を更新"""
        if side == "BUY":
            self.strategy.mark_position_filled(grid_level, order_id)
        elif side == "SELL":
            self.strategy.mark_position_closed(grid_level, order_id)

    # ── 注文登録・価格調整 ──────────────────────────────────────────

    def _register_and_handle(
        self, order: dict, grid_level: int, side: str, price: float, quantity: float
    ) -> None:
        """注文を登録し、即約定なら戦略を更新"""
        avg_price = float(order.get("avgPrice") or order["price"])
        executed_qty = float(order.get("executedQty") or order["origQty"])

        grid = self.strategy.grids[grid_level]
        if order["status"] == "FILLED":
            # 即約定は _active_orders に入れない（二重処理防止）
            if side == "BUY":
                self.strategy.mark_position_filled(grid_level, order["orderId"])
                grid.filled_quantity = executed_qty
            else:
                self.strategy.mark_position_closed(grid_level, order["orderId"])
            logger.info(f"グリッド {grid_level}: 即約定 @ {avg_price}")
        else:
            self.register_order(
                order_id=order["orderId"],
                grid_level=grid_level,
                side=side,
                price=avg_price,
                quantity=executed_qty,
                status=order["status"],
            )
            if side == "BUY":
                grid.buy_order_id = order["orderId"]
            else:
                grid.sell_order_id = order["orderId"]
            logger.info(f"グリッド {grid_level}: {side}注文配置 @ {price}, qty={quantity}")
