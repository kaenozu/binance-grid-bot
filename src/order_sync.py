"""起動時の注文同期

ファイルの役割: 取引所のオープン注文と、内部状態を同期
なぜ存在するか: Bot再起動時に未完了の注文を復元するため
関連ファイル: bot.py（メインループ）, order_manager.py（注文管理）, persistence.py（永続化）
"""

from utils.logger import setup_logger

logger = setup_logger("order_sync")


def sync_with_exchange(order_manager, strategy, risk_manager=None) -> tuple[int, int]:
    """取引所のオープン注文と内部状態を同期

    グリッドにマッチしない孤児注文は安全のためキャンセルする。

    Args:
        order_manager: OrderManager インスタンス
        strategy: GridStrategy インスタンス
        risk_manager: RiskManager インスタンス（ポジションカウント同期用）

    Returns:
        (registered_count, removed_count) 同期結果
    """
    try:
        open_orders = order_manager.client.get_open_orders(strategy.symbol)
    except Exception as e:
        logger.error(f"オープン注文取得失敗: {e}")
        return 0, 0

    exchange_ids = {o["orderId"] for o in open_orders}
    internal_ids = order_manager.get_active_order_ids()

    removed = 0
    for oid in list(internal_ids - exchange_ids):
        order_manager.remove_order(oid)
        removed += 1
    if removed:
        logger.info(f"内部にのみ存在する注文を削除: {removed} 件")

    registered = 0
    unmatched = 0
    for order in open_orders:
        oid = order["orderId"]
        if oid not in internal_ids:
            side = order["side"]
            price = float(order["price"])
            quantity = float(order.get("origQty", 0))
            status = order["status"]
            grid_level = _match_order_to_grid(price, strategy, side)
            if grid_level is not None:
                order_manager.register_order(
                    order_id=oid,
                    grid_level=grid_level,
                    side=side,
                    price=price,
                    quantity=quantity,
                    status=status,
                )
                if status == "FILLED":
                    if side == "BUY":
                        strategy.mark_position_filled(grid_level, oid)
                        if risk_manager:
                            risk_manager.record_position_open()
                    elif side == "SELL":
                        strategy.mark_position_closed(grid_level, oid)
                        if risk_manager:
                            risk_manager.record_position_close()
                registered += 1
            else:
                logger.warning(f"孤児注文を検出: {side} {price} (orderId={oid}) - キャンセルします")
                unmatched += 1
                try:
                    order_manager.client.cancel_order(strategy.symbol, oid)
                    logger.info(f"孤児注文をキャンセル: orderId={oid}")
                except Exception as e:
                    logger.error(f"孤児注文キャンセル失敗 orderId={oid}: {e}")

    if registered:
        logger.info(f"取引所からの注文を登録: {registered} 件")
    if unmatched:
        logger.warning(f"孤児注文キャンセル合計: {unmatched} 件")

    return registered, removed


def _match_order_to_grid(price: float, strategy, side: str) -> int | None:
    """注文価格に最も近いグリッドレベルを返す"""
    best_level: int | None = None
    best_diff = float("inf")

    grid_spacing = strategy.grid_spacing
    # 許容誤差をグリッド間隔の20%に制限（誤マッチング防止）
    tolerance = grid_spacing * 0.2

    for grid in strategy.grids:
        if side == "BUY":
            # 通常の買い（ポジションなし）またはショートの買い戻し（ショートポジションあり）
            if grid.position_filled and not grid.short_position_filled:
                continue
            diff = abs(grid.buy_price - price)
        elif side == "SELL":
            # 通常の売り（ポジションあり）またはショートの新規売り（ポジションなし）
            if not grid.position_filled and not grid.short_sell_price:
                continue
            
            # 通常の売り指値との比較
            if grid.sell_price is not None:
                diff = abs(grid.sell_price - price)
            # ショートの売り指値との比較（上方向グリッド）
            elif grid.short_sell_price is not None:
                diff = abs(grid.short_sell_price - price)
            else:
                continue
        else:
            continue

        if diff < best_diff:
            best_diff = diff
            best_level = grid.level

    if best_diff > tolerance:
        return None

    return best_level
