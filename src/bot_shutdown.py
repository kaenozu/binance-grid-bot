"""
ファイルパス: src/bot_shutdown.py
概要: ボット停止・エクスポート処理
説明: 停止時のエクスポート、オープンポジション決済、緊急停止のロジック
関連ファイル: src/bot.py, src/exporter.py, src/order_manager.py, src/portfolio.py
"""

from datetime import datetime
from pathlib import Path

from src import exporter
from utils.logger import setup_logger

logger = setup_logger("bot_shutdown")


def export_on_stop(portfolio):
    """停止時にトレード履歴をエクスポート"""
    if not portfolio.trades:
        return
    try:
        export_dir = Path("data") / "exports"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = export_dir / f"trades_{timestamp}.csv"
        json_path = export_dir / f"trades_{timestamp}.json"
        count = exporter.export_trades_csv(portfolio.trades, csv_path)
        exporter.export_trades_json(portfolio.trades, json_path)
        logger.info(f"トレード履歴をエクスポート: {count} 件 -> {export_dir}")
    except Exception as e:
        logger.error(f"エクスポート失敗: {e}")


def close_open_positions(client, strategy, portfolio):
    """オープンポジションを成行売却"""
    open_positions = [g for g in strategy.grids if g.position_filled]
    if not open_positions:
        return

    logger.warning(f"オープンポジション {len(open_positions)} 件を成行決済します")
    symbol_info = client.get_symbol_info(strategy.symbol)
    base_asset = symbol_info["base_asset"] if symbol_info else strategy.symbol.replace("USDT", "")
    step_size = symbol_info["step_size"] if symbol_info else 0
    min_qty = symbol_info["min_qty"] if symbol_info else 0
    min_notional = symbol_info["min_notional"] if symbol_info else 0
    try:
        balances = client.get_account_balance()
    except Exception as e:
        logger.error(f"残高取得失敗: {e}")
        return

    if base_asset not in balances:
        logger.error(f"残高がありません: {base_asset}")
        return

    available = balances[base_asset]["free"]
    if available <= 0:
        logger.warning(f"{base_asset} の残高がありません")
        return

    for grid in open_positions:
        if available <= 0:
            break
        try:
            qty_per_grid = strategy.get_order_quantity(
                grid.buy_price,
                min_qty=min_qty,
                step_size=step_size,
                min_notional=min_notional,
            )
            sell_qty = min(available, qty_per_grid)
            if sell_qty <= 0:
                continue

            result = client.place_order(
                symbol=strategy.symbol,
                side="SELL",
                quantity=sell_qty,
                price=None,
            )
            filled_qty = float(result.get("executedQty", result.get("origQty", sell_qty)))
            filled_price = float(result.get("avgPrice") or result.get("price", 0))
            portfolio.record_trade(
                side="SELL",
                price=filled_price,
                quantity=filled_qty,
                order_id=result["orderId"],
                grid_level=grid.level,
            )
            available -= filled_qty
            grid.position_filled = False
            grid.filled_quantity = None
            logger.info(f"グリッド {grid.level}: 緊急成行決済 {filled_qty} @ {filled_price}")
        except Exception as e:
            logger.error(f"グリッド {grid.level}: 緊急決済失敗: {e}")


def emergency_stop(client, strategy, order_manager, portfolio, persist_fn):
    """緊急停止処理（オープンポジションを成行決済して終了）"""
    logger.warning("緊急停止処理開始...")
    persist_fn()
    order_manager.cancel_all_orders()
    close_open_positions(client, strategy, portfolio)
    print(portfolio.generate_report())
    logger.info("緊急停止完了")


def stop_bot(
    client, strategy, order_manager, portfolio, persist_fn, close_positions, ws_client=None
):
    """ボット停止"""
    logger.info("ボット停止中...")

    if ws_client:
        ws_client.stop()

    persist_fn()

    canceled = order_manager.cancel_all_orders()
    logger.info(f"キャンセル完了: {canceled} 件")

    if close_positions:
        close_open_positions(client, strategy, portfolio)

    report = portfolio.generate_report()
    logger.info("\n" + report)

    export_on_stop(portfolio)

    logger.info("ボット停止完了")
