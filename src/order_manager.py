"""注文管理

ファイルの役割: グリッド注文的配置・約定チェック・キャンセルを管理
なぜ存在するか: ボットと取引所の間で注文状態を同期するための中心的クラス
関連ファイル: bot.py（メインループ）, binance_client.py（API通信）, grid_strategy.py（戦略）
"""

from dataclasses import dataclass, field

from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from utils.logger import setup_logger
from utils.precision import quantize_down, quantize_up

logger = setup_logger("order_manager")


def adjust_price(price: float, tick_size: float, side: str = "BUY") -> float:
    """価格をtick_sizeの倍数に調整

    BUY: 切り下げ（より低い指値で約定し易く）
    SELL: 切り上げ（より高い指値で約定し易く）

    Args:
        price: 調整前の価格
        tick_size: 価格精度（BinanceのtickSize）
        side: BUY または SELL

    Returns:
        tick_size の倍数に調整された価格。tick_size <= 0 の場合はそのまま返す。
    """
    if tick_size <= 0:
        return price
    if side == "BUY":
        return quantize_down(price, tick_size)
    return quantize_up(price, tick_size)


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
        """双方向グリッド注文を一括配置

        下方向: BUY below → SELL above（価格下落時に利益）
        上方向: SELL above → BUY back below（価格上昇時に利益）
        余剰: ベース資産の余りをSELL指値で活用
        """
        symbol_info = self.client.get_symbol_info(self.strategy.symbol)
        if not symbol_info:
            logger.error(f"シンボル情報取得失敗: {self.strategy.symbol}")
            return OrderPlacementResult(placed=0, errors=["シンボル情報取得失敗"])

        placed_count = 0
        errors: list[str] = []

        # ── 下方向: BUY指値（価格より下） ──
        for grid in self.strategy.get_active_buy_grids():
            if grid.position_filled:
                continue
            ok, err = self._try_place(grid.level, "BUY", grid.buy_price, symbol_info=symbol_info)
            if ok:
                placed_count += 1
            elif err:
                errors.append(err)

        # ── 下方向: SELL指値（ポジションあり） ──
        for grid in self.strategy.get_active_sell_grids():
            quantity = self._resolve_sell_quantity(grid, symbol_info)
            if grid.sell_price is not None:
                ok, err = self._try_place(
                    grid.level, "SELL", grid.sell_price, quantity, symbol_info=symbol_info
                )
                if ok:
                    placed_count += 1
                elif err:
                    errors.append(err)

        # ── 上方向: SELL指値（価格より上、手持ちSOLを売る） ──
        short_placed = self._place_short_sell_orders(symbol_info, errors)
        placed_count += short_placed

        # ── 上方向: BUYBACK指値（ショートポジションあり） ──
        for grid in self.strategy.get_active_short_buyback_grids():
            qty = grid.short_filled_quantity
            if qty and qty > 0 and grid.short_buyback_price is not None:
                ok, err = self._try_place(
                    grid.level, "BUY", grid.short_buyback_price, qty, symbol_info=symbol_info
                )
                if ok:
                    placed_count += 1
                elif err:
                    errors.append(err)

        logger.info(f"注文配置完了: {placed_count} 件, エラー: {len(errors)} 件")
        return OrderPlacementResult(placed=placed_count, errors=errors)

    def _place_short_sell_orders(self, symbol_info: dict, errors: list[str]) -> int:
        """価格より上のグリッドにSELL指値を配置（手持ちSOLを活用）

        SOLの余剰分を複数レベルに分割してSELL指値を出す。
        価格が上がったら約定 → 利益確定 → BUYBACKで買い戻す。
        """
        placed = 0
        try:
            balances = self.client.get_account_balance()
            base_asset = symbol_info.get("base_asset", "")
            available = float(balances.get(base_asset, {}).get("free", 0))
        except Exception:
            return 0

        if available <= 0:
            logger.debug(f"上方向SELL配置: {base_asset} 残高なし")
            return 0

        # 既存SELL注文でロック済みの数量を差し引く
        sell_locked = sum(o.quantity for o in self._active_orders.values() if o.side == "SELL")
        surplus = available - sell_locked
        surplus = self._normalize_quantity(surplus, symbol_info)
        if surplus <= 0:
            return 0

        # 上方向グリッドを取得
        short_grids = self.strategy.get_active_short_sell_grids()
        if not short_grids:
            return 0

        # 余剰SOLを各グリッドに均等分割
        qty_per_grid = surplus / len(short_grids)
        qty_per_grid = self._normalize_quantity(qty_per_grid, symbol_info)
        if qty_per_grid <= 0:
            # 全量を一番近いグリッドに
            qty_per_grid = surplus

        remaining = surplus
        for grid in short_grids:
            if remaining <= 0:
                break
            if grid.short_sell_price is None:
                continue
            qty = min(qty_per_grid, remaining)
            qty = self._normalize_quantity(qty, symbol_info)
            if qty <= 0:
                continue
            price = grid.short_sell_price
            assert price is not None, "short_sell_price must not be None"
            ok, err = self._try_place(grid.level, "SELL", price, qty, symbol_info=symbol_info)
            if ok:
                placed += 1
                remaining -= qty
            elif err:
                errors.append(err)

        if placed:
            base_asset = symbol_info.get("base_asset", "")
            logger.info(f"上方向SELL配置: {placed} 件 ({surplus:.6f} {base_asset}を分割)")
        return placed

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

    def handle_ws_fill(self, fill_info: dict) -> bool:
        """WebSocket からの約定通知を処理

        ポーリングによる約定検知の前に WS で検知できた場合、
        該当注文を即座にアクティブ注文から除去して重複処理を防ぐ。

        Args:
            fill_info: WS の ORDER_TRADE_UPDATE データ

        Returns:
            True: 新規約定として処理した、False: 既知または未知の注文
        """
        order_id = fill_info.get("order_id")
        if order_id is None:
            return False

        order = self._active_orders.get(order_id)
        if order is None:
            return False

        if order.status == "FILLED":
            return False

        order.status = "FILLED"
        logger.info(f"WS約定通知を処理: order_id={order_id}")
        return True

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
            per_grid_budget = self.strategy.investment_amount / self.strategy.grid_count
            quantity = self.strategy.get_order_quantity(
                grid.buy_price,
                symbol_info["min_qty"],
                symbol_info["step_size"],
                symbol_info.get("min_notional", 0),
                max_notional=per_grid_budget,
            )
        quantity = self._normalize_quantity(quantity, symbol_info)
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

    def _try_place(
        self,
        grid_level: int,
        side: str,
        price: float,
        quantity: float | None = None,
        symbol_info: dict | None = None,
    ) -> tuple[bool, str | None]:
        """注文を試行。成功=(True, None)、失敗=(False, error_msg)"""
        try:
            result = self._place_order(grid_level, side, price, quantity, symbol_info)
            if result is not None:
                return True, None
            return False, f"グリッド {grid_level} {side}: 数量無効でスキップ"
        except Exception as e:
            msg = f"グリッド {grid_level} {side}注文失敗: {e}"
            logger.error(msg)
            return False, msg

    def _resolve_sell_quantity(self, grid, symbol_info: dict) -> float:
        """売り注文の数量を解決（filled_quantity > buy_order > 計算値）"""
        if grid.filled_quantity is not None:
            return self._normalize_quantity(grid.filled_quantity, symbol_info)

        buy_order_id = grid.buy_order_id
        if buy_order_id and buy_order_id in self._active_orders:
            return self._normalize_quantity(self._active_orders[buy_order_id].quantity, symbol_info)

        return self._normalize_quantity(
            self.strategy.get_order_quantity(
                grid.buy_price,
                symbol_info["min_qty"],
                symbol_info["step_size"],
            ),
            symbol_info,
        )

    @staticmethod
    def _normalize_quantity(quantity: float, symbol_info: dict) -> float:
        """取引所制約に合わせて数量を丸める"""
        if quantity <= 0:
            return 0

        step_size = float(symbol_info.get("step_size", 0) or 0)
        min_qty = float(symbol_info.get("min_qty", 0) or 0)

        if step_size > 0:
            quantity = quantize_down(quantity, step_size)

        if min_qty > 0 and quantity < min_qty:
            return 0

        return quantity

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
        """取引所の openOrders を一括取得して約定を検出（API Weight 軽減）"""
        fills: list[FillEvent] = []
        filled_ids: set[int] = set()

        try:
            open_orders = self.client.get_open_orders(self.strategy.symbol)
        except Exception as e:
            logger.error(f"オープン注文一括取得失敗: {e}")
            return fills

        open_ids = {o["orderId"] for o in open_orders}
        candidates = set(self._active_orders.keys()) - open_ids

        for order_id in candidates:
            order_info = self._active_orders.get(order_id)
            if order_info is None:
                continue
            try:
                order = self.client.get_order(self.strategy.symbol, order_id)
                if order["status"] not in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                    continue
                if order["status"] != "FILLED":
                    logger.info(f"注文 {order_id} は {order['status']} により消失")
                    filled_ids.add(order_id)
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
            logger.info(f"約定/消失注文クリーンアップ: {len(filled_ids)} 件")
        return fills

    def _apply_fill_to_strategy(self, side: str, grid_level: int, order_id: int):
        """戦略のポジション状態を更新"""
        if side == "BUY":
            # BUYは下方向の買い戻しか、通常のBUYかを判定
            grid = self.strategy.grids[grid_level]
            if grid.short_position_filled and grid.short_buyback_order_id is None:
                self.strategy.mark_short_closed(grid_level, order_id)
            else:
                self.strategy.mark_position_filled(grid_level, order_id)
        elif side == "SELL":
            # SELLは上方向のショートか、通常の決済かを判定
            grid = self.strategy.grids[grid_level]
            if grid.short_sell_price and grid.short_sell_price > self.strategy.current_price:
                # 上方向グリッドのSELL → ショートポジション
                self.strategy.mark_short_filled(grid_level, order_id)
            else:
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
            if side == "BUY":
                if grid.short_position_filled:
                    self.strategy.mark_short_closed(grid_level, order["orderId"])
                else:
                    self.strategy.mark_position_filled(grid_level, order["orderId"])
                    grid.filled_quantity = executed_qty
            else:  # SELL
                if grid.short_sell_price and price >= grid.short_sell_price:
                    self.strategy.mark_short_filled(grid_level, order["orderId"])
                    grid.short_filled_quantity = executed_qty
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
