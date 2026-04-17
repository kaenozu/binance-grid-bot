"""起動時の注文同期

ファイルの役割: 取引所のオープン注文と、内部状態を同期
なぜ存在するか: Bot再起動時に未完了の注文を復元するため
関連ファイル: bot.py（メインループ）, order_manager.py（注文管理）, persistence.py（永続化）
"""

from utils.logger import setup_logger

logger = setup_logger("order_sync")


def sync_with_exchange(order_manager, strategy, risk_manager=None) -> tuple[int, int]:
    """取引所のオープン注文と内部状態を完全に同期・再構築

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
        logger.error(f"取引所からのオープン注文取得失敗: {e}")
        raise  # 起動失敗として扱うため例外を再送出

    # 現在の取引所注文 ID セット
    exchange_ids = {o["orderId"] for o in open_orders}
    # 内部管理注文 ID セット
    internal_ids = order_manager.get_active_order_ids()

    # 1. 取引所に存在しない内部注文をクリア
    removed = 0
    for oid in list(internal_ids - exchange_ids):
        order_manager.remove_order(oid)
        removed += 1
    if removed:
        logger.info(f"取引所に存在しない内部注文を削除: {removed} 件")

    # 2. 取引所の注文を内部へ強制登録
    registered = 0
    for order in open_orders:
        oid = order["orderId"]
        if oid in internal_ids:
            continue

        side = order["side"]
        price = float(order["price"])
        quantity = float(order.get("origQty", 0))
        status = order["status"]
        
        # グリッドマッチング（再構築）
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
            # ステータス同期
            if status == "FILLED":
                if side == "BUY":
                    strategy.mark_position_filled(grid_level, oid)
                    if risk_manager: risk_manager.record_position_open()
                elif side == "SELL":
                    strategy.mark_position_closed(grid_level, oid)
                    if risk_manager: risk_manager.record_position_close()
            registered += 1
        else:
            logger.error(f"同期失敗: 対応するグリッドが見つからない注文 (side={side}, price={price}, orderId={oid})")

    logger.info(f"注文同期完了: 新規登録={registered}, 削除={removed}")
    return registered, removed


def _match_order_to_grid(price: float, strategy, side: str) -> int | None:
    """注文価格に最も近いグリッドレベルを返す"""
    best_level: int | None = None
    best_diff = float("inf")

    grid_spacing = strategy.grid_spacing
    tolerance = grid_spacing * 0.5

    for grid in strategy.grids:
        if side == "BUY":
            if grid.position_filled:
                continue
            diff = abs(grid.buy_price - price)
        elif side == "SELL":
            if not grid.position_filled:
                continue
            if grid.sell_price is not None:
                diff = abs(grid.sell_price - price)
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
