"""ボットステータス表示

ファイルの役割: コンソールへのステータス表示
なぜ存在するか: 取引状況可視化のため
関連ファイル: bot.py（メインループ）, portfolio.py（統計）, risk_manager.py（リスク）
"""

from datetime import datetime

from utils.logger import setup_logger

logger = setup_logger("bot_display")


def display_status(
    symbol: str,
    current_price: float,
    grid_status: dict,
    stats,
    risk_status: dict,
    quote_asset: str = "USDT",
):
    """ステータスをログとCUIに表示"""
    lines = [
        "",
        "=" * 70,
        f"グリッドボット ステータス - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        f"取引ペア: {symbol}",
        f"現在価格: {current_price:.2f}",
        f"価格範囲: {grid_status['price_range']}",
        f"グリッド数: {grid_status['total_grids']} (間隔: {grid_status['grid_spacing']:.2f})",
        f"ポジション: {grid_status['filled_positions']}/{grid_status['total_grids']}",
        "-" * 70,
        f"初期残高: {stats.initial_balance:.2f} {quote_asset}",
        f"現在残高: {stats.current_balance:.2f} {quote_asset}",
        f"実現利益: {stats.realized_profit:+.2f} {quote_asset}",
        f"未実現利益: {stats.unrealized_profit:+.2f} {quote_asset}",
        f"累計手数料: {stats.total_fees:.2f} {quote_asset}",
        f"総利益: {stats.total_profit:+.2f} {quote_asset}",
        "-" * 70,
        f"取引回数: {stats.total_trades}",
        f"勝率: {stats.win_rate:.1f}%",
        f"損切りライン: {risk_status['stop_loss_price']:.2f}",
        f"ポジション: {risk_status['current_positions']}/{risk_status['max_positions']}",
        "=" * 70,
        "Ctrl+C で停止",
    ]
    output = "\n".join(lines)
    logger.info(output)
