"""ボット停止・緊急停止処理

ファイルパス: src/bot_shutdown.py
概要: 正常停止、緊急停止、オープンポジション決済、エクスポート
説明: ボット停止時に発生する一連の処理を統括
関連ファイル: src/bot.py, src/order_manager.py, src/portfolio.py,
            src/grid_strategy.py, src/binance_client.py, src/exporter.py
"""

from datetime import datetime
from pathlib import Path

from src import exporter
from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from src.order_manager import OrderManager
from src.portfolio import Portfolio
from utils.logger import setup_logger

logger = setup_logger("bot_shutdown")


def export_on_stop(portfolio: Portfolio) -> None:
    """停止時にトレード履歴をエクスポート

    Args:
        portfolio: Portfolio インスタンス
    """
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


def close_open_positions(
    client: BinanceClient,
    strategy: GridStrategy,
    portfolio: Portfolio,
) -> None:
    """オープンポジションを成行売却

    Args:
        client: BinanceClient インスタンス
        strategy: GridStrategy インスタンス
        portfolio: Portfolio インスタンス
    """
    open_positions = [g for g in strategy.grids if g.position_filled]
    if not open_positions:
        return

    logger.warning(f"オープンポジション {len(open_positions)} 件を成行決済します")
    symbol_info = client.get_symbol_info(strategy.symbol)
    base_asset = symbol_info["base_asset"] if symbol_info else strategy.symbol.replace("USDT", "")
    step_size = symbol_info["step_size"] if symbol_info else 0
    min_qty = symbol_info["min_qty"] if symbol_info else 0
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
            # grid.filled_quantity が実際の購入数量なので、それを卖出
            sell_qty = grid.filled_quantity if grid.filled_quantity else 0
            if symbol_info:
                # step_size に合わせて調整
                step = float(symbol_info.get("step_size", 0))
                if step > 0:
                    sell_qty = (sell_qty // step) * step
            sell_qty = min(available, sell_qty)
            if sell_qty <= 0:
                logger.warning(f"グリッド {grid.level}: 売却数量0、スキップ")
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
            logger.info(f"グリッド {grid.level}: 緊急成行決済 {filled_qty} @ {filled_price}")
        except Exception as e:
            logger.error(f"グリッド {grid.level}: 緊急決済失敗: {e}")


def emergency_stop(
    client: BinanceClient,
    strategy: GridStrategy,
    order_manager: OrderManager,
    portfolio: Portfolio,
    persist_fn,
) -> None:
    """緊急停止処理

    Args:
        client: BinanceClient インスタンス
        strategy: GridStrategy インスタンス
        order_manager: OrderManager インスタンス
        portfolio: Portfolio インスタンス
        persist_fn: 状態永続化関数
    """
    logger.warning("緊急停止処理開始...")
    persist_fn()
    order_manager.cancel_all_orders()
    close_open_positions(client, strategy, portfolio)
    print(portfolio.generate_report())
    logger.info("緊急停止完了")


def stop_bot(
    client: BinanceClient,
    strategy: GridStrategy,
    order_manager: OrderManager,
    portfolio: Portfolio,
    persist_fn,
    close_positions: bool,
    ws_client=None,
) -> None:
    """ボット停止

    Args:
        client: BinanceClient インスタンス
        strategy: GridStrategy インスタンス
        order_manager: OrderManager インスタンス
        portfolio: Portfolio インスタンス
        persist_fn: 状態永続化関数
        close_positions: ポジションを決済するか
        ws_client: WebSocket クライアント（オプション）
    """
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
