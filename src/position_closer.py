"""オープンポジションの成行決済

ファイルの役割: 停止時にポジションを成行で一括決済する
なぜ存在するか: 緊急停止・通常停止時の決済ロジックをbot.pyから分離するため
関連ファイル: bot.py（呼び出し元）, binance_client.py（API通信）, portfolio.py（記録）
"""

import math

from src.binance_client import BinanceClient
from src.grid_strategy import GridLevel, GridStrategy
from src.portfolio import Portfolio
from utils.logger import setup_logger

logger = setup_logger("position_closer")


def close_open_positions(
    client: BinanceClient,
    strategy: GridStrategy,
    portfolio: Portfolio,
) -> int:
    """オープンポジションを成行売却

    Args:
        client: Binance API クライアント
        strategy: グリッド戦略（grids を参照）
        portfolio: ポートフォリオ（トレード記録用）

    Returns:
        決済したポジション数
    """
    open_positions = sorted((g for g in strategy.grids if g.position_filled), key=lambda g: g.level)
    if not open_positions:
        return 0

    logger.warning(f"オープンポジション {len(open_positions)} 件を成行決済します")
    symbol_info = client.get_symbol_info(strategy.symbol)
    if not symbol_info:
        logger.error("シンボル情報取得失敗: 成行決済を中止します")
        return 0

    try:
        balances = client.get_account_balance()
    except Exception as e:
        logger.error(f"残高取得失敗: {e}")
        return 0

    base_asset = symbol_info["base_asset"]
    if base_asset not in balances:
        logger.error(f"残高がありません: {base_asset}")
        return 0

    available = balances[base_asset]["free"]
    min_qty = float(symbol_info.get("min_qty", 0) or 0)
    if available > 0 and min_qty > 0 and available < min_qty:
        logger.warning(
            f"{base_asset} の残高 {available} は最小数量 {min_qty} 未満のため、"
            "成行決済をスキップします"
        )
        return 0

    closed = 0
    for grid in open_positions:
        result, available = _close_single(client, strategy, portfolio, grid, available, symbol_info)
        closed += result

    return closed


def _close_single(
    client: BinanceClient,
    strategy: GridStrategy,
    portfolio: Portfolio,
    grid: GridLevel,
    available: float,
    symbol_info: dict,
) -> tuple[int, float]:
    """単一グリッドポジションの成行決済。成功=1、失敗=0を返す。"""
    try:
        qty = _resolve_close_quantity(portfolio, strategy, grid, symbol_info)
        if qty <= 0:
            return 0, available

        if available > 0 and available + 1e-12 < qty:
            logger.warning(
                f"グリッド {grid.level}: 残高 {available} {symbol_info['base_asset']} "
                f"より決済数量 {qty} の方が大きいため、スキップします"
            )
            return 0, available

        if not portfolio.find_matching_buy_trade(grid.level):
            portfolio.record_trade(
                side="BUY",
                price=grid.buy_price,
                quantity=qty,
                order_id=grid.buy_order_id or -1,
                grid_level=grid.level,
            )

        result = client.place_order(
            symbol=strategy.symbol, side="SELL", quantity=qty, price=None
        )
        filled_qty = float(result.get("executedQty", result.get("origQty", qty)))
        filled_price = float(result.get("avgPrice") or result.get("price", 0))
        portfolio.record_trade(
            side="SELL",
            price=filled_price,
            quantity=filled_qty,
            order_id=result["orderId"],
            grid_level=grid.level,
        )
        grid.position_filled = False
        grid.filled_quantity = None
        logger.info(f"グリッド {grid.level}: 緊急成行決済 {filled_qty} @ {filled_price}")
        remaining = max(0.0, available - filled_qty)
        return 1, remaining
    except Exception as e:
        logger.error(f"グリッド {grid.level}: 緊急決済失敗: {e}")
        return 0, available


def _resolve_close_quantity(
    portfolio: Portfolio,
    strategy: GridStrategy,
    grid: GridLevel,
    symbol_info: dict,
) -> float:
    """停止時に売却すべき数量を復元済み取引から決める"""
    qty = grid.filled_quantity
    if qty is None:
        matched_buy = portfolio.find_matching_buy_trade(grid.level)
        if matched_buy is not None:
            qty = matched_buy.quantity

    if qty is None:
        qty = strategy.get_order_quantity(
            grid.buy_price,
            min_qty=symbol_info["min_qty"],
            step_size=symbol_info["step_size"],
            min_notional=symbol_info["min_notional"],
        )

    return _normalize_quantity(qty, symbol_info)


def _normalize_quantity(quantity: float, symbol_info: dict) -> float:
    """成行決済用に数量を最小数量・stepSizeへ合わせる"""
    if quantity <= 0:
        return 0

    step_size = float(symbol_info.get("step_size", 0) or 0)
    min_qty = float(symbol_info.get("min_qty", 0) or 0)

    if step_size > 0:
        quantity = math.floor((quantity / step_size) + 1e-12) * step_size

    if min_qty > 0 and quantity < min_qty:
        return 0

    return quantity
