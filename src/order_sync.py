"""
ファイルパス: src/order_sync.py
概要: 起動時の注文同期
説明: 取引所のオープン注文と内部状態を突合する
関連ファイル: src/order_manager.py, src/grid_strategy.py
"""

from utils.logger import setup_logger

logger = setup_logger("order_sync")


def sync_with_exchange(order_manager, strategy):
    """取引所のオープン注文と内部状態を同期

    Args:
        order_manager: OrderManager インスタンス
        strategy: GridStrategy インスタンス

    Returns:
        (registered_count, removed_count) 同期結果
    """
    try:
        open_orders = order_manager.client.get_open_orders(strategy.symbol)
    except Exception as e:
        logger.error(f"オープン注文取得失敗: {e}")
        return 0, 0

    exchange_ids = {o["orderId"] for o in open_orders}
    internal_ids = set(order_manager._active_orders.keys())

    removed = 0
    for oid in list(internal_ids - exchange_ids):
        del order_manager._active_orders[oid]
        removed += 1
    if removed:
        logger.info(f"内部にのみ存在する注文を削除: {removed} 件")

    registered = 0
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
                    elif side == "SELL":
                        strategy.mark_position_closed(grid_level, oid)
                registered += 1

    if registered:
        logger.info(f"取引所からの注文を登録: {registered} 件")

    return registered, removed


def _match_order_to_grid(price: float, strategy, side: str) -> int:
    """注文価格に最も近いグリッドレベルを返す"""
    best_level = None
    best_diff = float("inf")

    grid_spacing = strategy.grid_spacing
    tolerance = grid_spacing * 0.5

    for grid in strategy.grids:
        if side == "BUY":
            diff = abs(grid.buy_price - price)
        elif side == "SELL" and grid.sell_price is not None:
            diff = abs(grid.sell_price - price)
        else:
            continue
        if diff < best_diff:
            best_diff = diff
            best_level = grid.level

    if best_diff > tolerance:
        return None

    return best_level
